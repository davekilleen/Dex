#!/usr/bin/env python3
"""One-time, pinned bootstrap for Dex lifecycle-era installations.

This is deliberately separate from an installed old Dex's update instructions.
Those releases can safely update the code they already contain, but cannot fetch
new Dex code. The bridge proves one predeclared foundation release and delegates
the topology conversion and release writes to its lifecycle service.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterator, Mapping, Protocol

OFFICIAL_REMOTE = "https://github.com/davekilleen/Dex.git"
_HEX = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_TAG = re.compile(r"^dist/release/v[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{7,40}$")
_APPROVAL_WORD = "APPLY"
_CLEAN_RUNTIME_MARKER = "DEX_UPDATE_BRIDGE_CLEAN_RUNTIME"
_TRUSTED_EXECUTABLE_DIRECTORIES = (Path("/usr/bin"), Path("/bin"), Path("/usr/local/bin"), Path("/opt/homebrew/bin"))
_TOPOLOGY_MIGRATOR_RELATIVE = Path("core/migrations/v1-to-v2-brain-vault-split.cjs")
_TRACKED_IGNORE_POLICY_RELATIVE = Path("core/migrations/tracked-ignored-policy.yaml")
_PRESERVATION_TRANSITION_RELATIVE = Path("System/.local-only-preservation-transition.json")
_LEGACY_SHIPPED_SYMLINK_RELATIVE = Path(".pi/agent/extensions/dex")
_LEGACY_SHIPPED_SYMLINK_TARGET = "../../../pi-extensions/dex"
_LEGACY_SHIPPED_SYMLINK_BLOB = "f1c88c92cea996705f982e902bafb758156aef52"
_PACKAGE_RELATIVE = Path("package.json")
_MANIFESTLESS_OMISSION_IDENTITIES = frozenset(
    {
        "af78f3d480b78b5bb558d873b98638c91d532de98f84f8f50e73448a1404b37d",
        "50a3e65dc2d65e6f6b28b30b630e06656d95ddd82f4a68a7152017119b110f90",
    }
)


def _manifestless_omission_identity(relative: str, raw_mode: str, object_id: str) -> str:
    """Return an opaque identity for one exact historical tree entry."""

    record = f"{raw_mode} blob {object_id}\t{relative}".encode()
    return hashlib.sha256(record).hexdigest()


def _manifestless_omission_identities_match(identities: set[str] | frozenset[str]) -> bool:
    """Accept only the complete closed omission set shipped by the pinned trees."""

    return frozenset(identities) == _MANIFESTLESS_OMISSION_IDENTITIES


class BridgeError(RuntimeError):
    """The bridge could not prove it is safe to continue."""


@dataclass(frozen=True)
class ReleasePin:
    """The closed immutable identity of the one bridge foundation release."""

    tag: str
    tag_object: str
    commit: str
    tree: str
    version: str

    def __post_init__(self) -> None:
        if _RELEASE_TAG.fullmatch(self.tag) is None:
            raise BridgeError("foundation tag is not an immutable distribution tag")
        if any(_HEX.fullmatch(value) is None for value in (self.tag_object, self.commit, self.tree)):
            raise BridgeError("foundation release identity is malformed")
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", self.version):
            raise BridgeError("foundation release version is malformed")
        if not self.tag.startswith(f"dist/release/v{self.version}-"):
            raise BridgeError("foundation tag and version disagree")

    def identity(self) -> dict[str, str]:
        return {
            "tag": self.tag,
            "tag_object": self.tag_object,
            "commit": self.commit,
            "tree": self.tree,
            "version": self.version,
            # ``release`` is the Git ref name; lifecycle identities name the
            # user-facing channel as ``stable``.
            "channel": "stable",
        }


# The first public release with the corrected self-delivery approval boundary
# and profile-safe package. This pin is intentionally in the bridge source:
# discovering a mutable "latest" release would not be a safe bootstrap.
FOUNDATION = ReleasePin(
    tag="dist/release/v1.81.0-6bc490e",
    tag_object="54b1ceef8b1f7ad4f67e4d4d045a134ea443ab53",
    commit="6bc490e7caec22f60f097c6b54bb563382f542b8",
    tree="dad3e43774e772dfc42df698f8a9818956346d78",
    version="1.81.0",
)


@dataclass(frozen=True)
class LegacyTopologyPin:
    """One immutable legacy tree allowed to use the foundation migrator."""

    tag: str
    tag_object: str
    commit: str
    tree: str


LEGACY_TOPOLOGY_FOUNDATION = LegacyTopologyPin(
    tag="v1.20.1",
    tag_object="3f7338dbe21ec98c015a3c8417d037cdd51b517d",
    commit="9e6f35d3282cb354008a4e7372b1cdb1d469ad3d",
    tree="b781bb94e417b2873d057a5a417d8c666a360bca",
)
_LEGACY_V1201_PACKAGE_SHA256 = "d0f3908ba0f6268d23c182acc1b3ef5b7557b92791635ff315eb6e324529f7ec"


@dataclass(frozen=True)
class HistoricReleasePin:
    """One exact published historical tree used by a read-only adapter."""

    tag: str
    tag_object: str
    tag_object_type: str
    commit: str
    tree: str
    version: str
    package_blob: str
    package_sha256: str

    def __post_init__(self) -> None:
        semantic = re.fullmatch(r"v(?P<version>[0-9]+\.[0-9]+\.[0-9]+)", self.tag)
        distribution = _RELEASE_TAG.fullmatch(self.tag)
        if semantic is None and distribution is None:
            raise BridgeError("historic release tag is malformed")
        if semantic is not None and semantic.group("version") != self.version:
            raise BridgeError("historic semantic tag and version disagree")
        if distribution is not None and not self.tag.startswith(f"dist/release/v{self.version}-"):
            raise BridgeError("historic distribution tag and version disagree")
        if self.tag_object_type not in {"commit", "tag"}:
            raise BridgeError("historic tag object type is malformed")
        if any(_HEX.fullmatch(value) is None for value in (self.tag_object, self.commit, self.tree, self.package_blob)):
            raise BridgeError("historic release identity is malformed")
        if not re.fullmatch(r"[0-9a-f]{64}", self.package_sha256):
            raise BridgeError("historic package identity is malformed")


MANIFESTLESS_SEMANTIC_RELEASES = (
    HistoricReleasePin(
        "v1.20.1",
        "3f7338dbe21ec98c015a3c8417d037cdd51b517d",
        "tag",
        "9e6f35d3282cb354008a4e7372b1cdb1d469ad3d",
        "b781bb94e417b2873d057a5a417d8c666a360bca",
        "1.20.1",
        "524e4fc38b6ef0b266776fd52023e41e603fa4a1",
        _LEGACY_V1201_PACKAGE_SHA256,
    ),
    HistoricReleasePin(
        "v1.49.0",
        "930adabf3e88b6534b3c90a9ad386151c1e291e4",
        "commit",
        "930adabf3e88b6534b3c90a9ad386151c1e291e4",
        "0a153375382907fd25a68d7c1845851d0d1f9946",
        "1.49.0",
        "32c22a6a13f1444beb8ce62a30ce6309b70244be",
        "acb472fb40dfb883c32b67fb07834de384154fd19697e90689cf16dfbf47621e",
    ),
    HistoricReleasePin(
        "v1.51.0",
        "c8069c90c1715bc7a10aced19ef95e3657089bfd",
        "commit",
        "c8069c90c1715bc7a10aced19ef95e3657089bfd",
        "8129f1a2d66a6a9d412cb6a3d919af725b160e6f",
        "1.51.0",
        "887ddacba2ff3e99b4293c50b522b112e8e7b8e0",
        "9518a9e1c162dd6ca8cdea484fc8081be2097edeeec2d3807b7b3d77b0283ebb",
    ),
    HistoricReleasePin(
        "v1.52.0",
        "0b843163815dab2bd9d0d4797a70f7c59864e76f",
        "commit",
        "0b843163815dab2bd9d0d4797a70f7c59864e76f",
        "faebf21f5c14dc10a2ac9b28856040425e6a24a8",
        "1.52.0",
        "34227d365e65fde32a61830c0b77cd6331fb3e7b",
        "64faaa5fcc8e1e77c12ed27d1b5f0c4ed5033d3d68029e94d7d9e9bdfc294cce",
    ),
    HistoricReleasePin(
        "v1.53.0",
        "a0bbd82d4a7c825b94c2e5467d3d34f8f2129280",
        "commit",
        "a0bbd82d4a7c825b94c2e5467d3d34f8f2129280",
        "59a50aba122ef8213544dc99ba36fd19cc78b5c1",
        "1.53.0",
        "d21587d1eb2e23562428fa72d4d7fb9e0a586b97",
        "1387699217fcc824db0a24517cc30fbe55ccbb4b24af9fce8eabb7ea886485e3",
    ),
    HistoricReleasePin(
        "v1.54.0",
        "3956d3710645492975d66f8f481c806c72533453",
        "commit",
        "3956d3710645492975d66f8f481c806c72533453",
        "ce724d55e677ef126a5f1ed4aa03f48236379327",
        "1.54.0",
        "113903345c57bf43ad4c2f991af866f0e1183da9",
        "64c64e97a995e7d0570d32b6e5dcb7743ef5394f6eefac09102aea8fe9e45b5d",
    ),
    HistoricReleasePin(
        "v1.55.0",
        "a023581a86b56ef97577513092001ea565832e17",
        "commit",
        "a023581a86b56ef97577513092001ea565832e17",
        "754789c0721bcb9bd82f43055afa8f09be0fda28",
        "1.55.0",
        "2b1c2330ad98ca6ca85fb3319a59d7b6835f8368",
        "ef626306a279cbef8f288f9ffd922d4fdb02c4095efc805df04348229f98cb12",
    ),
    HistoricReleasePin(
        "v1.56.0",
        "69505741999ab493f4f23733e33a9ffb2395c4bf",
        "commit",
        "69505741999ab493f4f23733e33a9ffb2395c4bf",
        "255083281de057f9dd07bdfe2c3e94be1e1de5ce",
        "1.56.0",
        "90bbdde25254fd3a9ceb3c4221337d9b3b39008f",
        "510a898356a7cad6b0efcd07ad49411a9881ae11e9ab3f2e06e08513b672dee0",
    ),
    HistoricReleasePin(
        "v1.57.0",
        "e5220bf72689e4434697aaa06978cac31cc9d5ee",
        "commit",
        "e5220bf72689e4434697aaa06978cac31cc9d5ee",
        "68af3dbebc0cbac8699dfa6d9fecf41b11852785",
        "1.57.0",
        "f6e66582be2bd845ebc6bdf3e7166ada6a4c0d1b",
        "c7478d3a64f1bf05ba6a29d2473fd72fe745d59029e943a267db329976fe09ff",
    ),
    HistoricReleasePin(
        "v1.58.0",
        "b001eb4048d413e1c68213f83b2c3ca2ad818a17",
        "commit",
        "b001eb4048d413e1c68213f83b2c3ca2ad818a17",
        "da2ee15b6490452d85eaf8a7fd883f92b743bea9",
        "1.58.0",
        "d25d36733053bd92f7f6d86fae9e0a887adb0bbc",
        "3e70ba4f05ed921f9015a610348ee6886fed19832b43a9cced2982088b206234",
    ),
    HistoricReleasePin(
        "v1.59.0",
        "f3a4413d6a1bc245250e23b4f5868953620b7237",
        "commit",
        "f3a4413d6a1bc245250e23b4f5868953620b7237",
        "9ecb0a55dd44c16b82a06ac1a02a1ee1a872607e",
        "1.59.0",
        "5cf1c327e9eec8c42d578c3da9bb6520f7b5fe18",
        "3ae65b8c0bdeea9e1c483459f9b902b484f01e04f32cc667fbd6300a8e87cebb",
    ),
    HistoricReleasePin(
        "v1.60.0",
        "6c986d80280e15af26b9cc4412c4578461b916db",
        "commit",
        "6c986d80280e15af26b9cc4412c4578461b916db",
        "6906f751bbb058db9bd4aee01e745459661c7131",
        "1.60.0",
        "7bbc92cdcfc2fd023861fb30d474e129f885913a",
        "c63aab865609555c3904879b4793245b5b67713e250add31273a505dd990c946",
    ),
    HistoricReleasePin(
        "v1.61.0",
        "b7c74d877b2aca4cb70ab343173f444feca612d0",
        "commit",
        "b7c74d877b2aca4cb70ab343173f444feca612d0",
        "0dda073b96be4955312445a089c625cc902738ca",
        "1.61.0",
        "884cf4421e2c3d74a8717f707fd3ac83c4bbc8fb",
        "30056d4dcf5a32208bc12e001b8f5b8c81b38f9499704ed47149569e7a6cdf38",
    ),
)

V161_RETIRED_MANIFEST_RELEASE = HistoricReleasePin(
    "dist/release/v1.61.0-774437a",
    "d1325426421fc0228865b2a64c8e780f2b8056ed",
    "tag",
    "774437aadfdb85bf834e2c2e1eacca6488364c18",
    "c3a71ece867e43c88dd30b8166c6087da2b344f2",
    "1.61.0",
    "b5e268bfd8bfe62e3efbe5a141e8dbb020d73609",
    "20d095aedcad0a13bd6b25ea183afcd5d367c438adb082b1044c582fb5c2ebf9",
)
_V161_RETIRED_MANIFEST_BLOB = "feef2bb3dd6756c7c54d76bdfd6128904c87f679"
_V161_RETIRED_MANIFEST_SHA256 = "edf6e98bc16063c47b362280cfa33fd10f075a5d240d5884d5ded5d894cbcc63"
_V161_RETIRED_MANIFEST_PATH_COUNT = 768

V175_DEFECTIVE_MANIFEST_RELEASE = HistoricReleasePin(
    "v1.75.0",
    "5e73481519ee9b5fe9a6c3196ee7cabaa0446ee8",
    "commit",
    "5e73481519ee9b5fe9a6c3196ee7cabaa0446ee8",
    "382b92df5b3a14da90e9122956353f589f2fc0b7",
    "1.75.0",
    "1cacd5c174cfc309e855bd54ae96bcf04afa4079",
    "fec3b6816d52f4f08c45f41e19b264b5d7dbc3844defc76186791a7f1d850308",
)
_V175_DEFECTIVE_MANIFEST_OMISSIONS = {
    "core/customization_migration/__init__.py": "9fae2734c7f4e1b42c569f6df73a43ef90fb253e",
    "core/customization_migration/inventory.py": "e96ae8a94544291aa28b37446655df65b76e7741",
    "core/customization_migration/model.py": "ce26945a12d1e68e50ac4d7693b38c3aadb218dc",
    "core/customization_migration/planning.py": "134f4707644842831731042308cba7fc30db55aa",
    "core/customization_migration/references.py": "f4269d559a53d009e69f8f2d0b83293e43105bb4",
    "core/customization_migration/report.py": "6ffee5daffea929af450245f49f75b16293b0f09",
    "core/customization_migration/service.py": "fba73a430cfe6a4537f390f1f5b6423c64c1a074",
    "core/tests/test_customization_assessment.py": "8a339e39e646fccb9f6c9babe64d9b62ccc5b0c6",
    "core/tests/test_customization_assessment_doctor.py": "b15ce6ebff890fa04ea60be3564848c8d4e252b9",
    "core/tests/test_customization_assessment_planning.py": "e29f5d97a506912af85e1c107237faad85f8b44d",
    "core/tests/test_lifecycle_topology_migration.py": "5cb2ae955cc575498284d4a96eb675b33ea3a4ba",
    "docs/customization-migration-threat-model.md": "f8fad1a1b5b5e249f66240fc32fa6c592ebd964f",
    "docs/plans/2026-07-24-customization-migration-mcp.md": "27ec0f3ff56c32bcc7960021f3b534414589272a",
}


@dataclass(frozen=True)
class UnboundJourneySourcePin:
    """One exact semantic source whose journey files predate the catalog bind."""

    release: HistoricReleasePin
    artifacts: tuple[tuple[str, str, str], ...]


V181_UNBOUND_JOURNEY_SOURCE = UnboundJourneySourcePin(
    release=HistoricReleasePin(
        "v1.81.0",
        "0f23787a22aa52afb40878df05e4819f77d179e6",
        "commit",
        "0f23787a22aa52afb40878df05e4819f77d179e6",
        "03e1832add6a27bc6c6dc833bfdba2b6cf7fd524",
        "1.81.0",
        "f54091ab0c0d543c848bb1344b8a0048c067b89f",
        "c4a8d1f0ebab0fb73656027812457f2c8f948e39be13b1eeca4bbcb33742a1bb",
    ),
    artifacts=(
        (
            "System/.installed-files.manifest",
            "1264aba3b8f1cff516caeb277380c09be1973e99",
            "fdd28af603f7575efcfe358472a60d0513b08d2f0f7aecf8395f7a0da27ea8ca",
        ),
        (
            "core/update/journey-protocol-v1.json",
            "d707e5d251a38333bcd2e8c658f543eac5cd75bf",
            "a8a99cc5766f83e9ed4daaac2d3173175736805b486cd028da04ae98b2dc15c0",
        ),
        (
            "scripts/release_fleet.py",
            "4da97ce6837d24a4b837bc3fcc29a30236b71b49",
            "6f44f9a718a066e3964a7a502f8ef0f2fb193214ccc58874f0059bc5af033a19",
        ),
        (
            "scripts/release_fleet_executor.py",
            "b97af897a3be095463ea7c3627b1b46ed0d5931f",
            "e90690babcaba9648b14fbf9cc18b79ff3e98ed92b806aa89855b842baf72205",
        ),
        (
            "scripts/dex_update_bridge.py",
            "16a95863f5ece67c9b700f243451e6b3f18b6dfa",
            "0d40463658d3f760e0f5a24061e1ff642306d1604d3cef8c5d9f89c97f4b7d9b",
        ),
    ),
)


@dataclass(frozen=True)
class ExistingInputTuple:
    """Exact existing inputs that may be replaced in-memory for one child."""

    policy_blob: str
    policy_sha256: str
    transition_blob: str
    transition_sha256: str


_INPUT_A_STALE_BOOTSTRAP = ExistingInputTuple(
    "35fa3d86020fe7b22768c199379508ddb4cef992",
    "4d7d0b4940afd1e0b0891801f75db2dce925ea6893cde82176aa0abe5b4c1872",
    "f76bf2a54600dd4ee8553664c9b9f36c4111e489",
    "f7073cf418c2ea7504f2bf1030d84d5a85be1b90f42f14895959e8318ff34e4e",
)
_INPUT_B_V162_BOOTSTRAP = ExistingInputTuple(
    "b2dfd209e83ecfed1d1f7fcc90be4e3444f08b2e",
    "caf6c54e8172ecc3d8f92a13fb6a739dddb8e9965e24bfa5a6e29d08f412aa5d",
    "8cec307895b102363a85992f5f3f5a2c7b0d3730",
    "31f90404e5898913b14d61a470489ac307abfd6877e313d2d714e2204b3037f7",
)
_INPUT_B_V163_BOOTSTRAP = ExistingInputTuple(
    "b2dfd209e83ecfed1d1f7fcc90be4e3444f08b2e",
    "caf6c54e8172ecc3d8f92a13fb6a739dddb8e9965e24bfa5a6e29d08f412aa5d",
    "cffb865aafcda0d20e66082f9c5eab4323f7b664",
    "d4fe097c6be47b5ca6198fbca412959c9777da2e6cafb863235be73c71a376a9",
)
_INPUT_B_V163_UNTRACK = ExistingInputTuple(
    "b2dfd209e83ecfed1d1f7fcc90be4e3444f08b2e",
    "caf6c54e8172ecc3d8f92a13fb6a739dddb8e9965e24bfa5a6e29d08f412aa5d",
    "91069155a2b5d14409d927af8708556f424740bd",
    "afd7f6338561ecd3597f32552e594f14630028f9ced64755f6dc11249b43d7a4",
)


@dataclass(frozen=True)
class MissingMigratorPin:
    release: HistoricReleasePin
    inputs: ExistingInputTuple


def _historic_pin(
    tag: str,
    tag_object: str,
    commit: str,
    tree: str,
    version: str,
    package_blob: str,
    package_sha256: str,
) -> HistoricReleasePin:
    return HistoricReleasePin(tag, tag_object, "tag", commit, tree, version, package_blob, package_sha256)


MISSING_MIGRATOR_RELEASES = (
    MissingMigratorPin(
        _historic_pin(
            "dist/release/v1.61.0-03c33d3",
            "b278bc51278c5b141dd65883fec920c8cb92d17a",
            "03c33d3c956557d1077ae2606168732a2c05bfb0",
            "f4e950f8266bd770ff99ce59f4b0de02ae8f2e19",
            "1.61.0",
            "b5e268bfd8bfe62e3efbe5a141e8dbb020d73609",
            "20d095aedcad0a13bd6b25ea183afcd5d367c438adb082b1044c582fb5c2ebf9",
        ),
        _INPUT_A_STALE_BOOTSTRAP,
    ),
    MissingMigratorPin(
        _historic_pin(
            "dist/release/v1.61.0-a010533",
            "6ecc9ea45be51d6040466072eeedef9a26dda15f",
            "a010533278912f092e6920447846f2c7b3402abe",
            "3cd446661d70a9f2bc5f9fcd58083efbd2f4b436",
            "1.61.0",
            "b5e268bfd8bfe62e3efbe5a141e8dbb020d73609",
            "20d095aedcad0a13bd6b25ea183afcd5d367c438adb082b1044c582fb5c2ebf9",
        ),
        _INPUT_A_STALE_BOOTSTRAP,
    ),
    MissingMigratorPin(
        _historic_pin(
            "dist/release/v1.61.0-dc7d332",
            "113ea147d484da0c2eb3bd80e35fa934388b095e",
            "dc7d332bed63589982664eca493da925cd1da6ce",
            "75f5fd9ae7baa05ee775093661e258746a18b0fb",
            "1.61.0",
            "b5e268bfd8bfe62e3efbe5a141e8dbb020d73609",
            "20d095aedcad0a13bd6b25ea183afcd5d367c438adb082b1044c582fb5c2ebf9",
        ),
        _INPUT_A_STALE_BOOTSTRAP,
    ),
    MissingMigratorPin(
        _historic_pin(
            "dist/release/v1.62.0-5a4fc2a",
            "e031be627ae35606770cee498f1101f050e75ef6",
            "5a4fc2a5a00f8523c231d840cbe9b2decb9b101e",
            "d51076f79dfac62020f83fa9430defe2ca605201",
            "1.62.0",
            "eefff9e671693d8eba2a1bb97a4f146923542ddf",
            "0d9912852060bae981c74dff56d24d1b12cdc5125a73b2c4c87d61bf51c787a4",
        ),
        _INPUT_A_STALE_BOOTSTRAP,
    ),
    MissingMigratorPin(
        _historic_pin(
            "dist/release/v1.62.0-6de410c",
            "5e954b3e10e52a48024b6030d3125d35d4699fb3",
            "6de410cce1b7bb80a4195940092bd5e82d7c32cf",
            "c0d5374d8e0494df461f012458b937fae797d007",
            "1.62.0",
            "eefff9e671693d8eba2a1bb97a4f146923542ddf",
            "0d9912852060bae981c74dff56d24d1b12cdc5125a73b2c4c87d61bf51c787a4",
        ),
        _INPUT_A_STALE_BOOTSTRAP,
    ),
    MissingMigratorPin(
        _historic_pin(
            "dist/release/v1.62.0-ba4862f",
            "7157ae8defde2e8698e5b6900bf4c6d9394b16d3",
            "ba4862f55813d34ab7ec6970507dc40e3ef8027f",
            "235168077df9621db3fcddfb677633bdcc946723",
            "1.62.0",
            "eefff9e671693d8eba2a1bb97a4f146923542ddf",
            "0d9912852060bae981c74dff56d24d1b12cdc5125a73b2c4c87d61bf51c787a4",
        ),
        _INPUT_A_STALE_BOOTSTRAP,
    ),
    MissingMigratorPin(
        _historic_pin(
            "dist/release/v1.62.0-cebe07b",
            "6b5f8f663c08613d5c8c49308bc1d08326e02a8f",
            "cebe07b23d6ceabf286ad31a24ce1aed23321c29",
            "4ec6aad8d9d162ccc489fbf7a9ff4b37f3e83b95",
            "1.62.0",
            "eefff9e671693d8eba2a1bb97a4f146923542ddf",
            "0d9912852060bae981c74dff56d24d1b12cdc5125a73b2c4c87d61bf51c787a4",
        ),
        _INPUT_A_STALE_BOOTSTRAP,
    ),
    MissingMigratorPin(
        _historic_pin(
            "dist/release/v1.62.0-d1ff64c",
            "ff0cd2c781a9689e26b0ba207e408649bf02fff1",
            "d1ff64c7f8938cb81b548bc7238c4cc9dc398a64",
            "feba9f46177dd802b698d5acd60896282b1508ff",
            "1.62.0",
            "eefff9e671693d8eba2a1bb97a4f146923542ddf",
            "0d9912852060bae981c74dff56d24d1b12cdc5125a73b2c4c87d61bf51c787a4",
        ),
        _INPUT_A_STALE_BOOTSTRAP,
    ),
    MissingMigratorPin(
        _historic_pin(
            "dist/release/v1.62.0-d5bd522",
            "2abdc01c6a78b1a69eb7484dae151f646c603adc",
            "d5bd522bccc3d17498d3c0c1e437ca0909c975a4",
            "3de9d2ec9884d4c97c471ecbf32236572fb8d496",
            "1.62.0",
            "eefff9e671693d8eba2a1bb97a4f146923542ddf",
            "0d9912852060bae981c74dff56d24d1b12cdc5125a73b2c4c87d61bf51c787a4",
        ),
        _INPUT_B_V162_BOOTSTRAP,
    ),
    MissingMigratorPin(
        _historic_pin(
            "dist/release/v1.63.0-6167d6e",
            "041d65c0e5706b191eea172fbe59762f66cbf3c9",
            "6167d6ef82d1607ed65b7b795538eb4ccdb23cbe",
            "c3e961ac5cbef45d762962ecd50b4fafbdece958",
            "1.63.0",
            "036655ee0687f89a309b6ac18e763996e719695c",
            "c7d1e58bfcf635af6703dc519546b12ed7538a34ee298d493b3db373cb495c98",
        ),
        _INPUT_B_V163_UNTRACK,
    ),
    MissingMigratorPin(
        _historic_pin(
            "dist/release/v1.63.0-d1050f4",
            "d4a49d6be2e5bdccf6ceee3cc6f016524e4d02bc",
            "d1050f47598a1625205dc571313dc3d4d08cfcd3",
            "b18cee1e7f61d4873c0748bd48396d7aa9ccd985",
            "1.63.0",
            "036655ee0687f89a309b6ac18e763996e719695c",
            "c7d1e58bfcf635af6703dc519546b12ed7538a34ee298d493b3db373cb495c98",
        ),
        _INPUT_B_V163_BOOTSTRAP,
    ),
    MissingMigratorPin(
        _historic_pin(
            "v1.62.0",
            "4913a778452003fcf8dc71a10222d5275ff28d5c",
            "77c4a15a7884080e48b095c8de2c384d01a87883",
            "1bf30a86c151890024040f0e4e1a533be17c5686",
            "1.62.0",
            "2d7f21a72798d4189f042e955e62ee799e90a90c",
            "75bef63d563a7e5062db6ad664ccb65a7581dbfd3d466655d1b3709bbad7ffa5",
        ),
        _INPUT_A_STALE_BOOTSTRAP,
    ),
    MissingMigratorPin(
        _historic_pin(
            "v1.63.0",
            "eff2f060455f186fcd27f5e680825051baf037b7",
            "b5ee55366f3600b79748a9b56e063a9825172a45",
            "a418102a6d8254a14c81575d1d86aea7d28bd6f8",
            "1.63.0",
            "846e23a1dd09c7096784268b234fde7139915575",
            "2f13e9f4f765dbe18a68a6fbe4b58f211eccecd50deba60e45647fdef0b9f6cf",
        ),
        _INPUT_B_V163_BOOTSTRAP,
    ),
)


def historic_missing_migrator_pins() -> dict[str, dict[str, object]]:
    """Return the exact existing-input, missing-migrator failure cohort."""

    return {
        compatibility.release.tag: {
            "kind": "existing-inputs-missing-migrator",
            "role": "installed-source",
            "tag": compatibility.release.tag,
            "tag_object": compatibility.release.tag_object,
            "commit": compatibility.release.commit,
            "tree": compatibility.release.tree,
            "version": compatibility.release.version,
            "package_blob": compatibility.release.package_blob,
            "package_sha256": compatibility.release.package_sha256,
            "policy_blob": compatibility.inputs.policy_blob,
            "policy_sha256": compatibility.inputs.policy_sha256,
            "transition_blob": compatibility.inputs.transition_blob,
            "transition_sha256": compatibility.inputs.transition_sha256,
            "migrator_blob": None,
            "migrator_state": "absent",
            "overwrite_existing_inputs": False,
        }
        for compatibility in MISSING_MIGRATOR_RELEASES
    }


def historic_missing_migrator_for(evidence: Mapping[str, object]) -> str | None:
    """Authorize only one complete exact existing-input failure identity."""

    if not isinstance(evidence, Mapping):
        return None
    supplied = dict(evidence)
    for name, pin in historic_missing_migrator_pins().items():
        if supplied == pin:
            return name
    return None

_NATIVE_MIGRATOR_BLOB = "57da3fa834ed1f9069f0187dd19b3e3e6f5b5580"
_NATIVE_MIGRATOR_SHA256 = "7c825da3c2cb38c7327431f237c3bf95c08f9e47b907555afa37b85cda7ec19f"
_NATIVE_INSTALL_BLOB = "f1ce82fa657786a3b9cae0526a8a8757531f6f39"
NATIVE_MIGRATOR_TRANSPORT_RELEASES = (
    _historic_pin(
        "dist/release/v1.63.0-08ce719",
        "492b56c53dbe469dcac93c7d9a85081026f04132",
        "08ce719d595809808e202fa4a7a5fbc68c1b5257",
        "87467beec1c11e91ff1bc27223d310b32b9b4978",
        "1.63.0",
        "036655ee0687f89a309b6ac18e763996e719695c",
        "c7d1e58bfcf635af6703dc519546b12ed7538a34ee298d493b3db373cb495c98",
    ),
    _historic_pin(
        "dist/release/v1.63.0-2f006c9",
        "25e579ea946e8b493fcec0d2e49aec5cdb9c1141",
        "2f006c95adcb566ee6ce881ffb534628ade49d02",
        "cfe29096d001d08ba77a9a649c9999d40f250c6e",
        "1.63.0",
        "036655ee0687f89a309b6ac18e763996e719695c",
        "c7d1e58bfcf635af6703dc519546b12ed7538a34ee298d493b3db373cb495c98",
    ),
    _historic_pin(
        "dist/release/v1.63.0-9a0660f",
        "d5123c4438c97b5c0e630dddad049f66389d3bc7",
        "9a0660f785b4f6d0c15ab3a77b346bb522e80eb7",
        "d4bc25fed1798db4e362506b60627da4b4fa97ad",
        "1.63.0",
        "036655ee0687f89a309b6ac18e763996e719695c",
        "c7d1e58bfcf635af6703dc519546b12ed7538a34ee298d493b3db373cb495c98",
    ),
    _historic_pin(
        "dist/release/v1.63.0-9dc6e3d",
        "05553ca6f04a2b89a3efbbea9d4901c63b74ae1f",
        "9dc6e3dfafd75b23c40607171787bd028099f6d1",
        "582bef8eebf62d171c63354b5cf4c618f2ac5593",
        "1.63.0",
        "036655ee0687f89a309b6ac18e763996e719695c",
        "c7d1e58bfcf635af6703dc519546b12ed7538a34ee298d493b3db373cb495c98",
    ),
)


def historic_compatibility_pins() -> dict[str, dict[str, object]]:
    """Return the closed installed-source compatibility ledger."""

    pins: dict[str, dict[str, object]] = {}
    for release in MANIFESTLESS_SEMANTIC_RELEASES:
        pins[release.tag] = {
            "kind": "manifestless-missing-migrator",
            "role": "installed-source",
            "tag": release.tag,
            "tag_object": release.tag_object if release.tag_object_type == "tag" else None,
            "commit": release.commit,
            "tree": release.tree,
            "package_blob": release.package_blob,
            "manifest_blob": None,
            "policy_blob": None,
            "transition_blob": None,
            "migrator_blob": None,
            "unexpected_nonregular_paths": (),
        }
    pins["v1.20.1"]["shipped_symlink"] = {
        "path": _LEGACY_SHIPPED_SYMLINK_RELATIVE.as_posix(),
        "blob": _LEGACY_SHIPPED_SYMLINK_BLOB,
        "target": _LEGACY_SHIPPED_SYMLINK_TARGET,
    }
    retired_manifest = V161_RETIRED_MANIFEST_RELEASE
    pins[retired_manifest.tag] = {
        "kind": "complete-manifest-retired-paths",
        "role": "installed-source",
        "tag": retired_manifest.tag,
        "tag_object": retired_manifest.tag_object,
        "commit": retired_manifest.commit,
        "tree": retired_manifest.tree,
        "version": retired_manifest.version,
        "package_blob": retired_manifest.package_blob,
        "package_sha256": retired_manifest.package_sha256,
        "manifest_blob": _V161_RETIRED_MANIFEST_BLOB,
        "manifest_sha256": _V161_RETIRED_MANIFEST_SHA256,
        "manifest_path_count": _V161_RETIRED_MANIFEST_PATH_COUNT,
        "policy_blob": None,
        "transition_blob": None,
        "migrator_blob": None,
        "omission_identities": tuple(sorted(_MANIFESTLESS_OMISSION_IDENTITIES)),
        "unexpected_nonregular_paths": (),
    }
    pins[V175_DEFECTIVE_MANIFEST_RELEASE.tag] = {
        "kind": "incomplete-manifest",
        "role": "installed-source",
        "tag": V175_DEFECTIVE_MANIFEST_RELEASE.tag,
        "tag_object": None,
        "commit": V175_DEFECTIVE_MANIFEST_RELEASE.commit,
        "tree": V175_DEFECTIVE_MANIFEST_RELEASE.tree,
        "package_blob": V175_DEFECTIVE_MANIFEST_RELEASE.package_blob,
        "manifest_blob": "6d2105eb1e33bd007ef8b4e2e77b927508a150f7",
        "manifest_sha256": "6a065ef3bcce45ac8e42d8143a4eb9e3516ea633fd0cbe8c3d2aff10a137ec34",
        "manifest_path_count": 1201,
        "omitted_paths": tuple(_V175_DEFECTIVE_MANIFEST_OMISSIONS),
        "omitted_paths_sha256": "b476b6a35ac869339e93f6451f13f6a09c6622b7be6ba73ee6e82bc404cc567d",
        "policy_blob": "b2dfd209e83ecfed1d1f7fcc90be4e3444f08b2e",
        "transition_blob": "2a016eafa4f2712343c3eea206b5be22259e3362",
        "migrator_blob": "559a870762bd8feb68aac7b6a9f93ec2f99d1efd",
        "unexpected_nonregular_paths": (),
    }
    source = V181_UNBOUND_JOURNEY_SOURCE.release
    pins[source.tag] = {
        "kind": "semantic-no-catalog",
        "role": "installed-source",
        "tag": source.tag,
        "tag_object": None,
        "commit": source.commit,
        "tree": source.tree,
        "package_blob": source.package_blob,
        "catalog_blob": None,
        "manifest_blob": "1264aba3b8f1cff516caeb277380c09be1973e99",
        "manifest_sha256": "fdd28af603f7575efcfe358472a60d0513b08d2f0f7aecf8395f7a0da27ea8ca",
        "manifest_path_count": 1297,
        "policy_blob": "7d1f2b3ace56e12fce2ff01fafe6435cd1b59e59",
        "transition_blob": "4b7ad8ff59d95a5e0af7106cb40f3aafa699400c",
        "migrator_blob": "c73fe7e186abbcd8dc588fa5c94d6244bf156662",
        "unexpected_nonregular_paths": (),
    }
    for release in NATIVE_MIGRATOR_TRANSPORT_RELEASES:
        pins[release.tag] = {
            "kind": "native-migrator-file-transport",
            "role": "installed-source",
            "tag": release.tag,
            "tag_object": release.tag_object,
            "commit": release.commit,
            "tree": release.tree,
            "package_blob": release.package_blob,
            "policy_blob": _INPUT_B_V163_UNTRACK.policy_blob,
            "transition_blob": _INPUT_B_V163_UNTRACK.transition_blob,
            "migrator_blob": _NATIVE_MIGRATOR_BLOB,
            "install_blob": _NATIVE_INSTALL_BLOB,
            "unexpected_nonregular_paths": (),
        }
    return pins


def historic_compatibility_for(evidence: Mapping[str, object]) -> str | None:
    """Authorize only a complete exact installed-source ledger entry."""

    if not isinstance(evidence, Mapping):
        return None
    supplied = dict(evidence)
    for name, pin in historic_compatibility_pins().items():
        if supplied == pin:
            return name
    return None


# v1.20.1 predates the tracked-ignore transition that the topology migrator
# reads before it can even build a preview. This is the complete baseline-v1
# policy first shipped for those historical paths, pinned here by byte hash.
# The compatibility preload exposes it read-only to the verified migrator; it
# never installs these newer release files into the old combined vault.
_LEGACY_TRACKED_IGNORE_POLICY = b"""schema_version: 2
active_baseline_version: 1
baselines:
  - baseline_version: 1
    baseline_count: 27
    paths:
      - path: 00-Inbox/Daily_Plans/README.md
        classification: intentional-seed
      - path: 00-Inbox/Ideas/README.md
        classification: intentional-seed
      - path: 00-Inbox/Meetings/README.md
        classification: intentional-seed
      - path: 00-Inbox/README.md
        classification: intentional-seed
      - path: 01-Quarter_Goals/Quarter_Goals.md
        classification: intentional-seed
      - path: 02-Week_Priorities/Week_Priorities.md
        classification: intentional-seed
      - path: 03-Tasks/Tasks.md
        classification: intentional-seed
      - path: 04-Projects/README.md
        classification: intentional-seed
      - path: 05-Areas/Career/Evidence/README.md
        classification: intentional-seed
      - path: 05-Areas/Companies/README.md
        classification: intentional-seed
      - path: 05-Areas/People/External/README.md
        classification: intentional-seed
      - path: 05-Areas/People/Internal/README.md
        classification: intentional-seed
      - path: 05-Areas/People/README.md
        classification: intentional-seed
      - path: 05-Areas/README.md
        classification: intentional-seed
      - path: 07-Archives/Plans/README.md
        classification: intentional-seed
      - path: 07-Archives/Projects/README.md
        classification: intentional-seed
      - path: 07-Archives/README.md
        classification: intentional-seed
      - path: 07-Archives/Reviews/README.md
        classification: intentional-seed
      - path: System/Dex_Backlog.md
        classification: intentional-seed
      - path: System/Session_Learnings/README.md
        classification: intentional-seed
      - path: System/pillars.yaml
        classification: intentional-seed
      - path: System/usage_log.md
        classification: intentional-seed
      - path: System/user-profile.yaml
        classification: intentional-seed
      - path: System/Beta_Communications/2026-02-04_hardcoded_paths_fix.md
        classification: release-doc
      - path: System/Session_Learnings/2026-01-29.md
        classification: local-only-must-be-untracked
      - path: System/Session_Learnings/2026-01-30.md
        classification: local-only-must-be-untracked
      - path: System/integrations/slack.yaml
        classification: local-only-must-be-untracked
"""
_LEGACY_TRACKED_IGNORE_POLICY_SHA256 = "bf0af119939930fb4d3b466584a3e9392edb66bf61ec09675521c9a5969f3f50"


def _legacy_preload_bytes() -> bytes:
    """Build the closed preload for absent or exact defective legacy inputs."""

    policy = base64.b64encode(_LEGACY_TRACKED_IGNORE_POLICY).decode("ascii")
    allowed_existing = json.dumps(
        sorted(
            {
                (
                    pin.release.version,
                    pin.release.package_sha256,
                    pin.inputs.policy_sha256,
                    pin.inputs.transition_sha256,
                )
                for pin in MISSING_MIGRATOR_RELEASES
            }
        ),
        separators=(",", ":"),
    )
    return f"""'use strict';
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

if (process.env.GIT_ALLOW_PROTOCOL !== 'https') {{
  throw new Error('Dex update bridge refused an unsafe inherited Git protocol policy.');
}}
// The pinned topology migrator uses only the vault's existing local Git store.
// Replace, rather than widen, the bridge's HTTPS policy inside this one child.
process.env.GIT_ALLOW_PROTOCOL = 'file';

const root = fs.realpathSync(process.cwd());
const shippedLink = path.join(root, '{_LEGACY_SHIPPED_SYMLINK_RELATIVE.as_posix()}');
const shippedLinkParent = path.dirname(shippedLink);
const shippedLinkName = path.basename(shippedLink);
const shippedLinkTarget = '{_LEGACY_SHIPPED_SYMLINK_TARGET}';
const transitionPath = path.join(root, '{_PRESERVATION_TRANSITION_RELATIVE.as_posix()}');
const packagePath = path.join(root, 'package.json');
const inputs = new Map([
  [path.join(root, '{_TRACKED_IGNORE_POLICY_RELATIVE.as_posix()}'), Buffer.from('{policy}', 'base64')],
]);
const allowedExisting = new Set({allowed_existing}.map((values) => values.join(':')));
const originalReadFileSync = fs.readFileSync.bind(fs);
const originalReaddirSync = fs.readdirSync.bind(fs);

function regularBytes(candidate, description) {{
  const state = fs.lstatSync(candidate);
  if (!state.isFile() || state.isSymbolicLink()) {{
    throw new Error(`Dex update bridge refused existing legacy compatibility input ${{candidate}} (${{description}} is unsafe).`);
  }}
  return originalReadFileSync(candidate);
}}

function digest(content) {{
  return crypto.createHash('sha256').update(content).digest('hex');
}}

function legacyTransition() {{
  const packageState = fs.lstatSync(packagePath);
  if (!packageState.isFile() || packageState.isSymbolicLink()) {{
    throw new Error(`Dex update bridge refused unsafe legacy package metadata ${{packagePath}}.`);
  }}
  const packageJson = JSON.parse(originalReadFileSync(packagePath, 'utf8'));
  if (
    !packageJson
    || typeof packageJson !== 'object'
    || Array.isArray(packageJson)
    || typeof packageJson.version !== 'string'
    || !/^[0-9]+\\.[0-9]+\\.[0-9]+$/.test(packageJson.version)
  ) {{
    throw new Error(`Dex update bridge refused invalid legacy package version ${{packagePath}}.`);
  }}
  return Buffer.from(`${{JSON.stringify({{
    phase: 'bootstrap-v1',
    release_version: packageJson.version,
    schema_version: 1,
  }})}}\\n`, 'utf8');
}}

function optionalState(candidate) {{
  try {{ return fs.lstatSync(candidate); }} catch (error) {{
    if (error && error.code === 'ENOENT') return null;
    throw error;
  }}
}}

function compatibilityInputs() {{
  const policyPath = [...inputs.keys()][0];
  const suppliedPolicy = [...inputs.values()][0];
  const policyState = optionalState(policyPath);
  const transitionState = optionalState(transitionPath);
  if (!policyState && !transitionState) {{
    return {{policy: suppliedPolicy, transition: legacyTransition()}};
  }}
  if (!policyState || !transitionState) {{
    throw new Error('Dex update bridge refused existing legacy compatibility input: partial tuple.');
  }}
  const packageBytes = regularBytes(packagePath, 'package metadata');
  let packageJson;
  try {{ packageJson = JSON.parse(packageBytes.toString('utf8')); }} catch (error) {{
    throw new Error(`Dex update bridge refused invalid legacy package metadata ${{packagePath}}.`);
  }}
  if (!packageJson || typeof packageJson.version !== 'string') {{
    throw new Error(`Dex update bridge refused invalid legacy package version ${{packagePath}}.`);
  }}
  const policyBytes = regularBytes(policyPath, 'tracked-ignore policy');
  const transitionBytes = regularBytes(transitionPath, 'preservation transition');
  const tuple = [
    packageJson.version,
    digest(packageBytes),
    digest(policyBytes),
    digest(transitionBytes),
  ].join(':');
  if (!allowedExisting.has(tuple)) {{
    throw new Error('Dex update bridge refused an unknown legacy compatibility tuple.');
  }}
  let transitionJson;
  try {{ transitionJson = JSON.parse(transitionBytes.toString('utf8')); }} catch (error) {{
    throw new Error('Dex update bridge refused invalid legacy transition metadata.');
  }}
  if (
    !transitionJson
    || transitionJson.schema_version !== 1
    || !['bootstrap-v1', 'untrack-v1'].includes(transitionJson.phase)
    || typeof transitionJson.release_version !== 'string'
  ) {{
    throw new Error('Dex update bridge refused invalid legacy transition metadata.');
  }}
  const virtualTransition = transitionJson.release_version === packageJson.version
    ? transitionBytes
    : legacyTransition();
  return {{policy: policyBytes, transition: virtualTransition}};
}}

let hideShippedLink = false;
let shippedLinkFound = false;
try {{
  const linkState = fs.lstatSync(shippedLink);
  shippedLinkFound = true;
  const resolvedTarget = fs.realpathSync(shippedLink);
  const expectedTarget = path.join(root, 'pi-extensions/dex');
  if (
    !linkState.isSymbolicLink()
    || fs.readlinkSync(shippedLink) !== shippedLinkTarget
    || resolvedTarget !== expectedTarget
    || !fs.lstatSync(expectedTarget).isDirectory()
  ) {{
    throw new Error(`Dex update bridge refused changed legacy release symlink ${{shippedLink}}.`);
  }}
  hideShippedLink = true;
}} catch (error) {{
  if (shippedLinkFound || !error || error.code !== 'ENOENT') throw error;
}}

fs.readFileSync = function dexLegacyCompatibilityRead(candidate, options) {{
  const supplied = Buffer.isBuffer(candidate) ? candidate.toString() : String(candidate);
  const absolute = path.resolve(supplied);
  const suppliedInput = inputs.has(absolute) || absolute === transitionPath;
  if (!suppliedInput) return originalReadFileSync(candidate, options);
  const suppliedInputs = compatibilityInputs();
  const content = absolute === transitionPath
    ? suppliedInputs.transition
    : suppliedInputs.policy;
  const encoding = typeof options === 'string' ? options : options && options.encoding;
  return encoding ? content.toString(encoding) : Buffer.from(content);
}};

fs.readdirSync = function dexLegacyCompatibilityDirectory(directory, options) {{
  const entries = originalReaddirSync(directory, options);
  if (
    hideShippedLink
    && path.resolve(String(directory)) === shippedLinkParent
    && options
    && typeof options === 'object'
    && options.withFileTypes === true
  ) {{
    return entries.filter((entry) => entry.name !== shippedLinkName);
  }}
  return entries;
}};
""".encode()


def _transport_preload_bytes() -> bytes:
    """Build a child-only protocol switch with no filesystem interception."""

    return b"""'use strict';
if (process.env.GIT_ALLOW_PROTOCOL !== 'https') {
  throw new Error('Dex update bridge refused an unsafe inherited Git protocol policy.');
}
process.env.GIT_ALLOW_PROTOCOL = 'file';
"""


class LifecycleService(Protocol):
    def build_and_preview_topology_migration(self, vault_root: str | Path) -> Mapping[str, Any]: ...
    def execute_approved_topology_migration(
        self, vault_root: str | Path, preview: Mapping[str, Any], approved_token: str
    ) -> Mapping[str, Any]: ...
    def build_and_preview_delivered_release(
        self, vault_root: str | Path, release: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...
    def execute_approved_delivered_release(
        self, vault_root: str | Path, preview: Mapping[str, Any], approved_token: str
    ) -> Mapping[str, Any]: ...
    def build_and_preview_mcp_registration(self, vault_root: str | Path) -> Mapping[str, Any]: ...
    def execute_approved_mcp_registration(
        self, vault_root: str | Path, preview: Mapping[str, Any], approved_token: str
    ) -> Mapping[str, Any]: ...


def _trusted_executable(name: str) -> Path | None:
    """Find a system-installed executable without consulting caller PATH."""
    for directory in _TRUSTED_EXECUTABLE_DIRECTORIES:
        candidate = directory / name
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    return None


def _trusted_git_binary() -> Path:
    git = _trusted_executable("git")
    if git is None:
        raise BridgeError("trusted system Git is required for the one-time Dex update bridge")
    return git


def _bridge_environment() -> dict[str, str]:
    """Return the small, non-interactive environment used by the bridge.

    The bridge fetches one public, pinned release; it must never inherit a
    caller's Git repository selection, configuration, credential helpers,
    Python import path, or executable lookup.  The foundation's Node migrator
    inherits this exact environment, so its Git children receive the same
    boundary.
    """
    executable_directories = [str(_trusted_git_binary().parent)]
    node = _trusted_executable("node")
    if node is not None:
        executable_directories.append(str(node.parent))
    executable_directories.extend(str(directory) for directory in _TRUSTED_EXECUTABLE_DIRECTORIES)
    return {
        "PATH": os.pathsep.join(dict.fromkeys(executable_directories)),
        "GCM_INTERACTIVE": "Never",
        "GIT_ALLOW_PROTOCOL": "https",
        "GIT_ASKPASS": "false",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _run_git(directory: Path, *arguments: str) -> str:
    """Run a non-interactive Git operation with hooks and non-HTTPS blocked."""
    completed = subprocess.run(
        [
            str(_trusted_git_binary()),
            "--no-replace-objects",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "credential.helper=",
            "-c",
            "fetch.fsckObjects=true",
            "-c",
            "transfer.fsckObjects=true",
            "-C",
            str(directory),
            *arguments,
        ],
        check=False,
        capture_output=True,
        env=_bridge_environment(),
        timeout=90,
    )
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise BridgeError(detail or "Git could not retrieve the pinned Dex release")
    try:
        return completed.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise BridgeError("Git returned non-text release metadata") from error


def _assert_equal(actual: str, expected: str, description: str) -> None:
    if actual != expected:
        raise BridgeError(f"pinned foundation {description} did not match")


def _verify_pin(repository: Path, pin: ReleasePin) -> None:
    _assert_equal(
        _run_git(repository, "rev-parse", "--verify", f"refs/tags/{pin.tag}"), pin.tag_object, "annotated tag"
    )
    _assert_equal(_run_git(repository, "rev-parse", "--verify", f"{pin.tag}^{{commit}}"), pin.commit, "commit")
    _assert_equal(_run_git(repository, "rev-parse", "--verify", f"{pin.tag}^{{tree}}"), pin.tree, "tree")


def _regular_sha256(path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _matches_historic_release(vault_root: Path, pin: HistoricReleasePin) -> bool:
    """Prove an exact tagged base plus its unchanged working package."""

    root = Path(vault_root)
    try:
        if (
            _run_git(
                root,
                "for-each-ref",
                "--format=%(objectname)",
                f"refs/tags/{pin.tag}",
            )
            != pin.tag_object
            or _run_git(root, "cat-file", "-t", pin.tag_object) != pin.tag_object_type
            or _run_git(root, "rev-parse", "--verify", f"{pin.tag}^{{commit}}") != pin.commit
            or _run_git(root, "rev-parse", "--verify", f"{pin.tag}^{{tree}}") != pin.tree
            or _run_git(
                root,
                "rev-parse",
                "--verify",
                f"{pin.commit}:{_PACKAGE_RELATIVE.as_posix()}",
            )
            != pin.package_blob
            or _regular_sha256(root / _PACKAGE_RELATIVE) != pin.package_sha256
        ):
            return False
        head = _run_git(root, "rev-parse", "--verify", "HEAD^{commit}")
        if _HEX.fullmatch(head) is None:
            return False
        _run_git(root, "merge-base", "--is-ancestor", pin.commit, head)
    except BridgeError:
        return False
    return True


def _matches_existing_inputs(vault_root: Path, pin: MissingMigratorPin) -> bool:
    root = Path(vault_root)
    try:
        if (
            _run_git(
                root,
                "rev-parse",
                "--verify",
                f"{pin.release.commit}:{_TRACKED_IGNORE_POLICY_RELATIVE.as_posix()}",
            )
            != pin.inputs.policy_blob
            or _run_git(
                root,
                "rev-parse",
                "--verify",
                f"{pin.release.commit}:{_PRESERVATION_TRANSITION_RELATIVE.as_posix()}",
            )
            != pin.inputs.transition_blob
        ):
            return False
    except BridgeError:
        return False
    return (
        _regular_sha256(root / _TRACKED_IGNORE_POLICY_RELATIVE) == pin.inputs.policy_sha256
        and _regular_sha256(root / _PRESERVATION_TRANSITION_RELATIVE) == pin.inputs.transition_sha256
    )


def _native_transport_release(vault_root: Path) -> HistoricReleasePin | None:
    """Return one of four exact native-migrator transport pins, or nothing."""

    root = Path(vault_root)
    for pin in NATIVE_MIGRATOR_TRANSPORT_RELEASES:
        if not _matches_historic_release(root, pin):
            continue
        try:
            if (
                _run_git(
                    root,
                    "rev-parse",
                    "--verify",
                    f"{pin.commit}:{_TOPOLOGY_MIGRATOR_RELATIVE.as_posix()}",
                )
                != _NATIVE_MIGRATOR_BLOB
                or _run_git(
                    root,
                    "rev-parse",
                    "--verify",
                    f"{pin.commit}:{_TRACKED_IGNORE_POLICY_RELATIVE.as_posix()}",
                )
                != _INPUT_B_V163_UNTRACK.policy_blob
                or _run_git(
                    root,
                    "rev-parse",
                    "--verify",
                    f"{pin.commit}:{_PRESERVATION_TRANSITION_RELATIVE.as_posix()}",
                )
                != _INPUT_B_V163_UNTRACK.transition_blob
            ):
                continue
        except BridgeError:
            continue
        if (
            _regular_sha256(root / _TOPOLOGY_MIGRATOR_RELATIVE) == _NATIVE_MIGRATOR_SHA256
            and _regular_sha256(root / _TRACKED_IGNORE_POLICY_RELATIVE) == _INPUT_B_V163_UNTRACK.policy_sha256
            and _regular_sha256(root / _PRESERVATION_TRANSITION_RELATIVE) == _INPUT_B_V163_UNTRACK.transition_sha256
        ):
            return pin
    return None


def exact_unbound_journey_source(
    repository: Path,
    tag: str,
    pin: UnboundJourneySourcePin = V181_UNBOUND_JOURNEY_SOURCE,
) -> str | None:
    """Resolve only the exact catalog-less v1.81 semantic source commit."""

    if tag != pin.release.tag:
        return None
    root = Path(repository)
    try:
        if (
            _run_git(root, "rev-parse", "--verify", f"refs/tags/{tag}") != pin.release.tag_object
            or _run_git(root, "cat-file", "-t", pin.release.tag_object) != "commit"
            or _run_git(root, "rev-parse", "--verify", f"{tag}^{{commit}}") != pin.release.commit
            or _run_git(root, "rev-parse", "--verify", f"{tag}^{{tree}}") != pin.release.tree
            or _run_git(root, "ls-tree", "-z", tag, "--", "System/.release-catalog.json")
        ):
            return None
        for relative, blob, _sha256 in pin.artifacts:
            if _run_git(root, "rev-parse", "--verify", f"{tag}:{relative}") != blob:
                return None
    except BridgeError:
        return None
    return pin.release.commit


def _supported_legacy_topology(
    vault_root: Path,
    pin: LegacyTopologyPin = LEGACY_TOPOLOGY_FOUNDATION,
) -> bool:
    """Prove the exact legacy base allowed to borrow the foundation migrator."""

    root = Path(vault_root)
    git_directory = root / ".git"
    if (
        git_directory.is_symlink()
        or not git_directory.is_dir()
        or (root / _TOPOLOGY_MIGRATOR_RELATIVE).exists()
        or (root / _TOPOLOGY_MIGRATOR_RELATIVE).is_symlink()
    ):
        return False
    package = root / _PACKAGE_RELATIVE
    if package.exists() or package.is_symlink():
        absent_inputs = (
            _TRACKED_IGNORE_POLICY_RELATIVE,
            _PRESERVATION_TRANSITION_RELATIVE,
            _TOPOLOGY_MIGRATOR_RELATIVE,
        )
        for release in MANIFESTLESS_SEMANTIC_RELEASES:
            if _matches_historic_release(root, release) and all(
                not (root / relative).exists() and not (root / relative).is_symlink() for relative in absent_inputs
            ):
                return True
        if _matches_historic_release(root, V161_RETIRED_MANIFEST_RELEASE) and all(
            not (root / relative).exists() and not (root / relative).is_symlink()
            for relative in absent_inputs
        ):
            return True
        for compatibility in MISSING_MIGRATOR_RELEASES:
            if _matches_historic_release(root, compatibility.release) and _matches_existing_inputs(root, compatibility):
                return True
    try:
        tag_object = _run_git(
            root,
            "for-each-ref",
            "--format=%(objectname)",
            f"refs/tags/{pin.tag}",
        )
        if tag_object:
            if tag_object != pin.tag_object:
                return False
            if _run_git(root, "cat-file", "-t", pin.tag_object) != "tag":
                return False
            identity = pin.tag
        else:
            # Historic installers retained their own release tag but could
            # prune older tag labels. The pinned commit remains a safe proof
            # only when its object type, commit identity, tree, and ancestry
            # all match the closed v1.20.1 foundation.
            if _run_git(root, "cat-file", "-t", pin.commit) != "commit":
                return False
            identity = pin.commit
        if _run_git(root, "rev-parse", "--verify", f"{identity}^{{commit}}") != pin.commit:
            return False
        if _run_git(root, "rev-parse", "--verify", f"{identity}^{{tree}}") != pin.tree:
            return False
        head = _run_git(root, "rev-parse", "--verify", "HEAD^{commit}")
        if _HEX.fullmatch(head) is None:
            return False
        _run_git(root, "merge-base", "--is-ancestor", pin.commit, head)
    except BridgeError:
        return False
    if package.exists() or package.is_symlink():
        return _regular_sha256(package) == _LEGACY_V1201_PACKAGE_SHA256
    return True


def acquire_foundation_source(pin: ReleasePin = FOUNDATION) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Fetch only the pinned foundation tag into a disposable source checkout."""
    temporary = tempfile.TemporaryDirectory(prefix="dex-update-bridge-")
    root = Path(temporary.name)
    bare = root / "evidence.git"
    source = root / "foundation"
    try:
        _run_git(root, "init", "--bare", "--quiet", str(bare))
        _run_git(
            bare,
            "fetch",
            "--quiet",
            "--no-tags",
            "--no-write-fetch-head",
            "--no-recurse-submodules",
            OFFICIAL_REMOTE,
            f"refs/tags/{pin.tag}:refs/tags/{pin.tag}",
        )
        _verify_pin(bare, pin)
        # A linked worktree keeps the verified objects in the disposable bare
        # evidence store. It avoids opening the local ``file`` transport, which
        # this bridge deliberately blocks for every network-facing Git call.
        _run_git(bare, "worktree", "add", "--quiet", "--detach", str(source), pin.tag)
        _verify_pin(source, pin)
    except Exception:
        temporary.cleanup()
        raise
    return temporary, source


def _validate_vault(vault_root: Path) -> Path:
    supplied = Path(vault_root).expanduser()
    if ".." in supplied.parts:
        raise BridgeError("Dex vault path must not contain parent-directory traversal")
    # ``resolve()`` follows links, so it is only safe after every component of
    # the path supplied by the caller has been checked.  Otherwise a symlinked
    # root would appear to be an ordinary target directory by the time the
    # lifecycle service sees it.
    lexical = Path(os.path.abspath(supplied))
    path_component = Path(lexical.anchor)
    for component in lexical.parts[1:]:
        path_component /= component
        if path_component.is_symlink():
            raise BridgeError("Dex vault path contains a symlink")
    root = lexical.resolve()
    if not root.is_dir():
        raise BridgeError("Dex vault is not a safe directory")
    if (root / ".git").is_symlink() or not (root / ".git").exists():
        raise BridgeError("Dex vault does not have a safe Git history")
    if (root / "System").is_symlink() or not (root / "System").is_dir():
        raise BridgeError("Dex vault does not have a safe System directory")
    for private_parent in (".venv", ".dex"):
        candidate = root / private_parent
        if candidate.is_symlink():
            raise BridgeError(f"Dex vault {private_parent} must not be a symlink")
        if candidate.exists() and not candidate.is_dir():
            raise BridgeError(f"Dex vault {private_parent} must be a directory")
    return root


def _installed_python(vault_root: Path) -> Path | None:
    """Return Dex's already-created POSIX virtualenv interpreter, if present.

    The foundation lifecycle service needs the same runtime dependencies that
    the historical Dex installer already put in ``.venv``.  The bridge never
    downloads Python packages at update time.  This is deliberately a POSIX
    seam; Windows gets its own reviewed bridge rather than guessed paths.
    """
    venv = vault_root / ".venv"
    if venv.is_symlink() or (venv.exists() and not venv.is_dir()):
        return None
    candidate = venv / "bin" / "python"
    config = venv / "pyvenv.cfg"
    # POSIX venvs normally expose Python as a symlink to the system interpreter;
    # executing that entrypoint is what makes its dependency site-packages
    # available, so reject only a missing/non-executable resolved target.
    if not candidate.exists() or not candidate.resolve().is_file() or not os.access(candidate, os.X_OK):
        return None
    if config.is_symlink() or not config.is_file():
        return None
    return candidate


def _running_in_selected_runtime(interpreter: Path) -> bool:
    """Prove this process was launched through the selected vault virtualenv.

    Virtualenv Python binaries may be symlinks to the host binary, so comparing
    resolved executables would accept a host-Python invocation.  Preserve the
    invocation path and require the virtualenv's runtime prefixes as well.
    """
    selected_prefix = interpreter.parent.parent
    return (
        os.path.abspath(sys.executable) == str(interpreter)
        and os.path.abspath(sys.prefix) == str(selected_prefix)
        and os.path.abspath(sys.exec_prefix) == str(selected_prefix)
    )


def _reexec_in_installed_runtime(vault_root: Path, argv: list[str]) -> None:
    """Enter one clean process before loading any foundation code.

    The installed venv can resolve to the same binary as the invoking Python,
    but running it by its venv path still selects the installed dependencies.
    Never trust a caller-supplied runtime marker: it is accepted only when the
    complete environment already equals the closed runtime environment and the
    running Python identifies as the selected vault virtualenv.
    """
    interpreter = _installed_python(vault_root)
    if interpreter is None:
        raise BridgeError("Dex's installed virtualenv is required for the one-time update bridge")
    environment = _bridge_environment()
    environment[_CLEAN_RUNTIME_MARKER] = "1"
    if (
        os.environ.get(_CLEAN_RUNTIME_MARKER) == "1"
        and dict(os.environ) == environment
        and _running_in_selected_runtime(interpreter)
    ):
        return
    os.execve(
        str(interpreter),
        [str(interpreter), str(Path(__file__).resolve()), *argv],
        environment,
    )


class _FoundationLifecycleService:
    """Bind a verified foundation migrator to one legacy lifecycle call.

    The foundation service normally launches the migrator shipped inside the
    vault. v1.20.1 predates that file. For only that exact immutable base, this
    adapter lets the same lifecycle preview/approval/execute path launch the
    migrator from the already-verified disposable foundation checkout. No
    bridge file is copied into the vault and unknown layouts stay fail-closed.
    """

    def __init__(
        self,
        service: ModuleType,
        engine: ModuleType,
        apply_update: ModuleType,
        source: Path,
    ) -> None:
        self._service = service
        self._engine = engine
        self._apply_update = apply_update
        self._source = Path(source).resolve()
        self._migrator = self._source / _TOPOLOGY_MIGRATOR_RELATIVE
        engine_relative = getattr(engine, "TOPOLOGY_MIGRATOR_RELATIVE", None)
        if not isinstance(engine_relative, Path) or engine_relative != _TOPOLOGY_MIGRATOR_RELATIVE:
            raise BridgeError("pinned foundation topology migrator path changed")
        if (
            self._migrator.is_symlink()
            or not self._migrator.is_file()
            or not self._migrator.resolve().is_relative_to(self._source)
        ):
            raise BridgeError("pinned foundation topology migrator is missing or unsafe")
        self._migrator_sha256 = hashlib.sha256(self._migrator.read_bytes()).hexdigest()
        if hashlib.sha256(_LEGACY_TRACKED_IGNORE_POLICY).hexdigest() != _LEGACY_TRACKED_IGNORE_POLICY_SHA256:
            raise BridgeError("pinned legacy tracked-ignore policy changed")
        compatibility = Path(
            tempfile.mkdtemp(
                prefix="dex-v1201-compat-",
                dir=self._source.parent,
            )
        )
        self._preload = compatibility / "read-only-inputs.cjs"
        with self._preload.open("xb") as handle:
            handle.write(_legacy_preload_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        self._preload.chmod(0o400)
        self._preload_sha256 = hashlib.sha256(self._preload.read_bytes()).hexdigest()
        self._transport_preload = compatibility / "file-transport-only.cjs"
        with self._transport_preload.open("xb") as handle:
            handle.write(_transport_preload_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        self._transport_preload.chmod(0o400)
        self._transport_preload_sha256 = hashlib.sha256(self._transport_preload.read_bytes()).hexdigest()
        if not callable(getattr(engine, "topology_state", None)) or not callable(
            getattr(engine, "_migrator_command", None)
        ):
            raise BridgeError("pinned foundation topology engine is incomplete")
        if not callable(getattr(apply_update, "_tree_entries", None)) or not callable(
            getattr(apply_update, "_verify_manifest", None)
        ):
            raise BridgeError("pinned foundation release planner is incomplete")

    def _verify_compatibility_runtime(self) -> None:
        if (
            self._migrator.is_symlink()
            or not self._migrator.is_file()
            or self._migrator.resolve().parent != (self._source / _TOPOLOGY_MIGRATOR_RELATIVE.parent).resolve()
            or hashlib.sha256(self._migrator.read_bytes()).hexdigest() != self._migrator_sha256
        ):
            raise BridgeError("pinned foundation topology migrator changed after verification")
        if (
            self._preload.is_symlink()
            or not self._preload.is_file()
            or not self._preload.resolve().is_relative_to(self._source.parent.resolve())
            or hashlib.sha256(self._preload.read_bytes()).hexdigest() != self._preload_sha256
        ):
            raise BridgeError("pinned legacy compatibility preload changed after verification")
        if (
            self._transport_preload.is_symlink()
            or not self._transport_preload.is_file()
            or not self._transport_preload.resolve().is_relative_to(self._source.parent.resolve())
            or hashlib.sha256(self._transport_preload.read_bytes()).hexdigest() != self._transport_preload_sha256
        ):
            raise BridgeError("pinned transport compatibility preload changed after verification")

    @contextmanager
    def _topology_source(self) -> Iterator[None]:
        self._verify_compatibility_runtime()
        original_state = self._engine.topology_state
        original_command = self._engine._migrator_command
        authorized_roots: set[Path] = set()
        transport_roots: set[Path] = set()

        def topology_state(vault_root: Path) -> str:
            state = original_state(vault_root)
            root = Path(vault_root).resolve()
            candidate = root / _TOPOLOGY_MIGRATOR_RELATIVE
            if state == "combined" and _native_transport_release(root) is not None:
                transport_roots.add(root)
            if (
                state == "invalid-combined"
                and not candidate.exists()
                and not candidate.is_symlink()
                and _supported_legacy_topology(root)
            ):
                authorized_roots.add(root)
                return "combined"
            return state

        def migrator_command(vault_root: Path, mode: str) -> list[str]:
            root = Path(vault_root).resolve()
            candidate = root / _TOPOLOGY_MIGRATOR_RELATIVE
            if (
                root in authorized_roots
                and not candidate.exists()
                and not candidate.is_symlink()
                and mode in {"--dry-run", "--auto", "--resume"}
            ):
                self._verify_compatibility_runtime()
                node = _trusted_executable("node")
                if node is None:
                    raise BridgeError("trusted system Node.js is required for the foundation topology migrator")
                return [
                    str(node),
                    "--require",
                    str(self._preload),
                    str(self._migrator),
                    mode,
                ]
            command = original_command(vault_root, mode)
            if root not in transport_roots:
                return command
            if (
                mode not in {"--dry-run", "--auto", "--resume"}
                or _native_transport_release(root) is None
                or len(command) != 3
                or Path(command[1]).resolve() != candidate.resolve()
                or command[2] != mode
            ):
                raise BridgeError("pinned native migrator transport identity changed")
            trusted_node = _trusted_executable("node")
            if trusted_node is None or Path(command[0]).resolve() != trusted_node:
                raise BridgeError("pinned native migrator selected an untrusted Node.js")
            self._verify_compatibility_runtime()
            return [
                command[0],
                "--require",
                str(self._transport_preload),
                command[1],
                command[2],
            ]

        self._engine.topology_state = topology_state
        self._engine._migrator_command = migrator_command
        try:
            yield
        finally:
            self._engine.topology_state = original_state
            self._engine._migrator_command = original_command

    @contextmanager
    def _legacy_delivery_source(self) -> Iterator[None]:
        """Let the planner read the one exact pre-manifest legacy release.

        Historic sources can have no manifest, one incomplete manifest, or one
        exact early manifest that still names two retired entries. The
        foundation planner correctly refuses those shapes for a modern target.
        For only the already-pinned installed trees, this read adapter omits
        closed entry identities. The lifecycle transaction remains the sole
        writer; omitted legacy paths stay in place as user-controlled/unmanaged
        content.
        """

        original_tree_entries = self._apply_update._tree_entries
        original_verify_manifest = self._apply_update._verify_manifest
        authorized_legacy_signatures: dict[tuple[tuple[str, int, str], ...], tuple[str, str]] = {}
        manifestless_by_commit = {pin.commit: pin for pin in MANIFESTLESS_SEMANTIC_RELEASES}
        release_error = getattr(
            self._apply_update,
            "ReleaseVerificationError",
            RuntimeError,
        )
        contract_violation = getattr(
            self._apply_update.portable_contract,
            "ContractViolation",
            RuntimeError,
        )
        tree_entry = getattr(self._apply_update, "TreeEntry", None)
        if not callable(tree_entry):
            raise BridgeError("pinned foundation release entry type is unavailable")

        def signature(entries: tuple[Any, ...]) -> tuple[tuple[str, int, str], ...]:
            return tuple((entry.path, entry.mode, entry.object_id) for entry in entries)

        def legacy_tree_entries(
            vault_root: Path,
            brain_git: Path,
            commit: str,
        ) -> tuple[Any, ...]:
            manifestless = manifestless_by_commit.get(commit)
            defective = V175_DEFECTIVE_MANIFEST_RELEASE if commit == V175_DEFECTIVE_MANIFEST_RELEASE.commit else None
            retired_manifest = (
                V161_RETIRED_MANIFEST_RELEASE
                if commit == V161_RETIRED_MANIFEST_RELEASE.commit
                else None
            )
            pin = manifestless or defective or retired_manifest
            if pin is None:
                return original_tree_entries(vault_root, brain_git, commit)
            if _run_git(Path(brain_git), "rev-parse", "--verify", f"{commit}^{{tree}}") != pin.tree:
                raise BridgeError("installed historic release tree changed before delivery")
            if retired_manifest is not None:
                try:
                    if (
                        _run_git(
                            Path(brain_git),
                            "rev-parse",
                            "--verify",
                            "refs/dex/installed^{commit}",
                        )
                        != retired_manifest.commit
                        or _run_git(Path(brain_git), "cat-file", "-t", retired_manifest.commit)
                        != "commit"
                        or _run_git(
                            Path(brain_git),
                            "rev-parse",
                            "--verify",
                            f"{retired_manifest.commit}:{_PACKAGE_RELATIVE.as_posix()}",
                        )
                        != retired_manifest.package_blob
                        or _run_git(
                            Path(brain_git),
                            "rev-parse",
                            "--verify",
                            f"{retired_manifest.commit}:System/.installed-files.manifest",
                        )
                        != _V161_RETIRED_MANIFEST_BLOB
                    ):
                        raise release_error("historic retired-manifest identity changed")
                except BridgeError as error:
                    raise release_error("historic retired-manifest identity changed") from error
            raw = self._apply_update._brain_output(
                vault_root,
                brain_git,
                "ls-tree",
                "-r",
                "-z",
                "--full-tree",
                commit,
            )
            entries: list[Any] = []
            seen: set[str] = set()
            omitted: set[str] = set()
            for record in raw.split(b"\0"):
                if not record:
                    continue
                try:
                    metadata, raw_path = record.split(b"\t", 1)
                    raw_mode, object_type, object_id = metadata.decode("ascii").split(" ")
                    relative = raw_path.decode("utf-8")
                except (ValueError, UnicodeDecodeError) as error:
                    raise release_error("legacy release tree contains a malformed entry") from error
                if relative in seen or object_type != "blob":
                    raise release_error("legacy release tree is ambiguous")
                seen.add(relative)
                if raw_mode == "120000":
                    if (
                        manifestless is None
                        or manifestless.commit != LEGACY_TOPOLOGY_FOUNDATION.commit
                        or relative != _LEGACY_SHIPPED_SYMLINK_RELATIVE.as_posix()
                        or object_id != _LEGACY_SHIPPED_SYMLINK_BLOB
                        or self._apply_update._brain_output(
                            vault_root,
                            brain_git,
                            "cat-file",
                            "blob",
                            object_id,
                        )
                        != _LEGACY_SHIPPED_SYMLINK_TARGET.encode()
                    ):
                        raise release_error("historic release contains an unknown symlink")
                    continue
                if raw_mode not in {"100644", "100755"}:
                    raise release_error("historic release contains an unsupported entry")
                if defective is not None and relative in _V175_DEFECTIVE_MANIFEST_OMISSIONS:
                    if raw_mode != "100644" or object_id != _V175_DEFECTIVE_MANIFEST_OMISSIONS[relative]:
                        raise release_error("historic defective-manifest omission changed")
                    omitted.add(relative)
                    continue
                omission_identity = _manifestless_omission_identity(relative, raw_mode, object_id)
                if (
                    (manifestless is not None or retired_manifest is not None)
                    and omission_identity in _MANIFESTLESS_OMISSION_IDENTITIES
                ):
                    omitted.add(omission_identity)
                    continue
                if manifestless is None and retired_manifest is None:
                    entries.append(
                        tree_entry(
                            relative,
                            0o755 if raw_mode == "100755" else 0o644,
                            object_id,
                        )
                    )
                    continue
                if retired_manifest is not None:
                    try:
                        self._apply_update.portable_contract.resolve(relative)
                    except contract_violation as error:
                        raise release_error(
                            "historic release contains an unknown unclassified path"
                        ) from error
                    entries.append(
                        tree_entry(
                            relative,
                            0o755 if raw_mode == "100755" else 0o644,
                            object_id,
                        )
                    )
                    continue
                try:
                    self._apply_update.portable_contract.resolve(relative)
                except contract_violation as error:
                    # Retired release paths that the current contract does not
                    # own are preserved only for the already-shipped v1.20.1
                    # exception. Later pins have only the two closed omissions.
                    if manifestless.commit == LEGACY_TOPOLOGY_FOUNDATION.commit:
                        continue
                    raise release_error("historic release contains an unknown unclassified path") from error
                entries.append(
                    tree_entry(
                        relative,
                        0o755 if raw_mode == "100755" else 0o644,
                        object_id,
                    )
                )
            if defective is not None and omitted != set(_V175_DEFECTIVE_MANIFEST_OMISSIONS):
                raise release_error("historic release omission set changed")
            if manifestless is not None and not _manifestless_omission_identities_match(omitted):
                raise release_error("historic manifestless omission set changed")
            if retired_manifest is not None:
                if not _manifestless_omission_identities_match(omitted):
                    raise release_error("historic retired-manifest omission set changed")
                complete = original_tree_entries(vault_root, brain_git, commit)
                original_verify_manifest(vault_root, brain_git, complete)
                by_path = {entry.path: entry for entry in complete}
                manifest_entry = by_path.get("System/.installed-files.manifest")
                if (
                    len(complete) != _V161_RETIRED_MANIFEST_PATH_COUNT
                    or manifest_entry is None
                    or manifest_entry.object_id != _V161_RETIRED_MANIFEST_BLOB
                    or hashlib.sha256(
                        self._apply_update._brain_output(
                            vault_root,
                            brain_git,
                            "cat-file",
                            "blob",
                            manifest_entry.object_id,
                        )
                    ).hexdigest()
                    != _V161_RETIRED_MANIFEST_SHA256
                ):
                    raise release_error("historic retired-manifest identity changed")
            result = tuple(sorted(entries, key=lambda entry: entry.path))
            authorized_legacy_signatures[signature(result)] = (
                pin.commit,
                (
                    "manifestless"
                    if manifestless is not None
                    else "retired-manifest"
                    if retired_manifest is not None
                    else "incomplete-manifest"
                ),
            )
            return result

        def verify_manifest(
            vault_root: Path,
            brain_git: Path,
            entries: tuple[Any, ...],
        ) -> None:
            authorization = authorized_legacy_signatures.get(signature(entries))
            if authorization is None:
                original_verify_manifest(vault_root, brain_git, entries)
                return
            installed = _run_git(
                Path(brain_git),
                "rev-parse",
                "--verify",
                "refs/dex/installed^{commit}",
            )
            if installed != authorization[0]:
                raise release_error("historic installed release identity changed")
            try:
                original_verify_manifest(vault_root, brain_git, entries)
            except release_error:
                if authorization[1] not in {"manifestless", "retired-manifest"}:
                    raise

        self._apply_update._tree_entries = legacy_tree_entries
        self._apply_update._verify_manifest = verify_manifest
        try:
            yield
        finally:
            self._apply_update._tree_entries = original_tree_entries
            self._apply_update._verify_manifest = original_verify_manifest

    def build_and_preview_topology_migration(
        self,
        vault_root: str | Path,
    ) -> Mapping[str, Any]:
        with self._topology_source():
            return self._service.build_and_preview_topology_migration(vault_root)

    def execute_approved_topology_migration(
        self,
        vault_root: str | Path,
        preview: Mapping[str, Any],
        approved_token: str,
    ) -> Mapping[str, Any]:
        with self._topology_source():
            return self._service.execute_approved_topology_migration(
                vault_root,
                preview,
                approved_token,
            )

    def deliver_latest_release(
        self,
        vault_root: str | Path,
    ) -> Mapping[str, Any]:
        return self._service.deliver_latest_release(vault_root)

    def build_and_preview_delivered_release(
        self,
        vault_root: str | Path,
        release: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        with self._legacy_delivery_source():
            return self._service.build_and_preview_delivered_release(
                vault_root,
                release,
            )

    def execute_approved_delivered_release(
        self,
        vault_root: str | Path,
        preview: Mapping[str, Any],
        approved_token: str,
    ) -> Mapping[str, Any]:
        with self._legacy_delivery_source():
            return self._service.execute_approved_delivered_release(
                vault_root,
                preview,
                approved_token,
            )

    def build_and_preview_mcp_registration(
        self,
        vault_root: str | Path,
    ) -> Mapping[str, Any]:
        return self._service.build_and_preview_mcp_registration(vault_root)

    def execute_approved_mcp_registration(
        self,
        vault_root: str | Path,
        preview: Mapping[str, Any],
        approved_token: str,
    ) -> Mapping[str, Any]:
        return self._service.execute_approved_mcp_registration(
            vault_root,
            preview,
            approved_token,
        )


def _load_lifecycle_service(source: Path) -> LifecycleService:
    """Import only the verified foundation release's lifecycle service."""
    if not (source / "core" / "lifecycle" / "service.py").is_file():
        raise BridgeError("pinned foundation release has no lifecycle service")
    for name in tuple(sys.modules):
        if name == "core" or name.startswith("core."):
            del sys.modules[name]
    sys.path.insert(0, str(source))
    try:
        module: ModuleType = importlib.import_module("core.lifecycle.service")
    except Exception as error:  # noqa: BLE001
        raise BridgeError(f"pinned foundation lifecycle service could not start: {error}") from error
    required = (
        "build_and_preview_topology_migration",
        "execute_approved_topology_migration",
        "deliver_latest_release",
        "build_and_preview_delivered_release",
        "execute_approved_delivered_release",
        "build_and_preview_mcp_registration",
        "execute_approved_mcp_registration",
    )
    if any(not callable(getattr(module, name, None)) for name in required):
        raise BridgeError("pinned foundation lifecycle service is incomplete")
    try:
        engine = importlib.import_module("core.lifecycle.engine")
    except Exception as error:  # noqa: BLE001
        raise BridgeError(f"pinned foundation topology engine could not start: {error}") from error
    try:
        apply_update = importlib.import_module("core.update.apply_update")
    except Exception as error:  # noqa: BLE001
        raise BridgeError(f"pinned foundation release planner could not start: {error}") from error
    return _FoundationLifecycleService(module, engine, apply_update, source)


def _approved_preview(
    prompt: str,
    preview: Mapping[str, Any],
    approval_token: object,
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> tuple[Mapping[str, Any], str]:
    if not isinstance(approval_token, str) or not approval_token:
        raise BridgeError("lifecycle preview did not return an approval token")
    output_fn(json.dumps(preview, indent=2, sort_keys=True))
    if input_fn(f"{prompt} Type {_APPROVAL_WORD} to continue: ") != _APPROVAL_WORD:
        raise BridgeError("no change was made because the displayed preview was not approved")
    return preview, approval_token


def _fetch_foundation_into_brain(vault_root: Path, pin: ReleasePin) -> None:
    """Fetch one pinned release into the private brain; no vault file is written.

    The public release branch is allowed to advance after the foundation ships.
    Only the closed immutable tag identifies the first hop.  Once verified, its
    exact commit becomes the private release ref consumed by lifecycle.
    """
    brain = vault_root / ".dex" / "brain.git"
    if brain.is_symlink() or not brain.is_dir():
        raise BridgeError("topology conversion did not create a safe Dex brain store")
    _run_git(
        brain,
        "fetch",
        "--quiet",
        "--no-tags",
        "--no-write-fetch-head",
        "--no-recurse-submodules",
        OFFICIAL_REMOTE,
        f"refs/tags/{pin.tag}:refs/tags/{pin.tag}",
    )
    _verify_pin(brain, pin)
    _run_git(
        brain,
        "update-ref",
        "refs/remotes/upstream/release",
        pin.commit,
    )
    _assert_equal(
        _run_git(brain, "rev-parse", "--verify", "refs/remotes/upstream/release^{commit}"),
        pin.commit,
        "private foundation release ref",
    )


def _regular_json(path: Path, description: str) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise BridgeError(f"{description} is not a regular file")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BridgeError(f"{description} is unreadable") from error
    if not isinstance(value, dict):
        raise BridgeError(f"{description} is not an object")
    return value


def _validate_completed_foundation(vault_root: Path, pin: ReleasePin) -> None:
    """Prove every durable split marker agrees with the installed pin."""
    brain = vault_root / ".dex" / "brain.git"
    paths = {
        ".git": vault_root / ".git",
        ".dex": vault_root / ".dex",
        ".dex/brain.git": brain,
        "System/.dex": vault_root / "System" / ".dex",
    }
    for relative, path in paths.items():
        if path.is_symlink() or not path.is_dir():
            raise BridgeError(f"completed bridge has an unsafe {relative} directory")

    topology = _regular_json(vault_root / "System" / ".dex" / "topology.json", "split topology marker")
    vault_marker = _regular_json(vault_root / ".git" / "dex-vault-v2", "vault Git marker")
    brain_marker = _regular_json(brain / "dex-brain-v2", "brain Git marker")
    environment = topology.get("environment")
    wired_vault = environment.get("DEX_VAULT") if isinstance(environment, dict) else None
    try:
        wiring_matches = isinstance(wired_vault, str) and Path(wired_vault).resolve() == vault_root
    except (OSError, RuntimeError):
        wiring_matches = False
    if (
        topology.get("topology") != "brain-vault-split"
        or topology.get("vaultGitDir") != ".git"
        or topology.get("brainGitDir") != ".dex/brain.git"
        or not wiring_matches
        or topology.get("installedRelease") != pin.commit
        or vault_marker.get("role") != "vault"
        or brain_marker.get("role") != "brain"
        or brain_marker.get("installed") != pin.commit
    ):
        raise BridgeError("completed bridge markers do not agree with the pinned foundation")


def _foundation_is_installed(vault_root: Path, pin: ReleasePin) -> bool:
    """Check the local installed ref without fetching or consulting a channel.

    This is deliberately safe to call before topology conversion: an old vault
    simply has no private brain store yet, whereas a completed bridge can
    resume offline even if the public stable channel has advanced.
    """
    brain = vault_root / ".dex" / "brain.git"
    dex_root = vault_root / ".dex"
    if dex_root.is_symlink() or brain.is_symlink():
        raise BridgeError("Dex private code store must not contain a symlink")
    if not dex_root.exists() or not brain.exists():
        return False
    if not dex_root.is_dir() or not brain.is_dir():
        raise BridgeError("Dex private code store is not a safe directory")
    try:
        installed = _run_git(brain, "rev-parse", "--verify", "refs/dex/installed^{commit}")
    except BridgeError:
        return False
    if installed != pin.commit:
        return False
    _validate_completed_foundation(vault_root, pin)
    return True


def _completed_bridge_result(
    pin: ReleasePin,
    mcp_registration_receipt: Mapping[str, Any],
) -> dict[str, object]:
    return {
        "foundation": pin.identity(),
        "topology_receipt": {"skipped": "foundation-already-installed"},
        "delivery_receipt": {"skipped": "foundation-already-installed"},
        "mcp_registration_receipt": dict(mcp_registration_receipt),
    }


def _complete_mcp_registration(
    vault_root: Path,
    service: LifecycleService,
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> Mapping[str, Any]:
    registration = service.build_and_preview_mcp_registration(vault_root)
    if registration.get("needed") is False:
        if registration.get("preview") is not None or registration.get("approval_token") is not None:
            raise BridgeError("foundation returned a malformed completed MCP registration")
        return {"skipped": "mcp-already-registered"}

    registration_preview = registration.get("preview")
    if registration.get("needed") is not True or not isinstance(
        registration_preview,
        Mapping,
    ):
        raise BridgeError("foundation could not produce an MCP registration preview")
    registration_preview, registration_token = _approved_preview(
        "Dex will add the current customization migration server to your MCP configuration.",
        registration_preview,
        registration.get("approval_token"),
        input_fn=input_fn,
        output_fn=output_fn,
    )
    return service.execute_approved_mcp_registration(
        vault_root,
        registration_preview,
        registration_token,
    )


def run_bridge(
    vault_root: Path,
    service: LifecycleService,
    *,
    pin: ReleasePin = FOUNDATION,
    fetch_foundation: Callable[[Path, ReleasePin], None] = _fetch_foundation_into_brain,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> Mapping[str, Any]:
    """Run up to three fresh approval boundaries through the foundation service."""
    root = _validate_vault(vault_root)
    # This local ref is the authoritative resume marker. Check it before
    # importing/calling lifecycle code or attempting any network operation: a
    # completed bridge must work offline and must not be disturbed merely
    # because the stable channel has subsequently advanced.
    if _foundation_is_installed(root, pin):
        return _completed_bridge_result(
            pin,
            _complete_mcp_registration(
                root,
                service,
                input_fn=input_fn,
                output_fn=output_fn,
            ),
        )

    topology = service.build_and_preview_topology_migration(root)
    preview = topology.get("preview")
    # Foundation v1.80.5 calls a completed conversion ``post-split`` and still
    # returns a read-only status document. Older service shapes used
    # ``brain-vault-split`` with no preview. Neither has an approval token, so
    # neither is an operation the bridge may repeat.
    if topology.get("topology") in {"brain-vault-split", "post-split"} and topology.get("approval_token") is None:
        topology_receipt: Mapping[str, Any] = {"skipped": "already-brain-vault-split"}
    else:
        if not isinstance(preview, Mapping):
            raise BridgeError("foundation could not produce a topology preview")
        preview, token = _approved_preview(
            "Dex will first separate its code from your notes.",
            preview,
            topology.get("approval_token"),
            input_fn=input_fn,
            output_fn=output_fn,
        )
        topology_receipt = service.execute_approved_topology_migration(root, preview, token)

    # This fetch touches only Dex's private code store. The following preview is
    # still the sole authority for every vault-content write.
    fetch_foundation(root, pin)
    delivery = service.build_and_preview_delivered_release(root, pin.identity())
    release_preview = delivery.get("preview")
    if not isinstance(release_preview, Mapping):
        raise BridgeError("foundation could not produce a delivered-release preview")
    release_preview, release_token = _approved_preview(
        f"Dex will now install verified foundation v{pin.version}.",
        release_preview,
        delivery.get("approval_token"),
        input_fn=input_fn,
        output_fn=output_fn,
    )
    delivery_receipt = service.execute_approved_delivered_release(root, release_preview, release_token)

    mcp_registration_receipt = _complete_mcp_registration(
        root,
        service,
        input_fn=input_fn,
        output_fn=output_fn,
    )

    return {
        "foundation": pin.identity(),
        "topology_receipt": dict(topology_receipt),
        "delivery_receipt": dict(delivery_receipt),
        "mcp_registration_receipt": dict(mcp_registration_receipt),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=Path.cwd(), help="old Dex vault (defaults to current directory)")
    args = parser.parse_args(argv)
    if sys.platform.startswith("win"):
        parser.error("this P0 bridge supports macOS and Linux only")
    try:
        _trusted_git_binary()
        vault = _validate_vault(args.vault)
        # A completed bridge has all durable state locally.  Check before
        # selecting the old virtualenv or downloading source so resuming it is
        # genuinely offline and independent of a later stable-channel change.
        if _foundation_is_installed(vault, FOUNDATION):
            _reexec_in_installed_runtime(
                vault,
                sys.argv[1:] if argv is None else argv,
            )
            result = run_bridge(
                vault,
                _load_lifecycle_service(vault),
            )
        else:
            _reexec_in_installed_runtime(vault, sys.argv[1:] if argv is None else argv)
            temporary, source = acquire_foundation_source()
            try:
                result = run_bridge(vault, _load_lifecycle_service(source))
            finally:
                temporary.cleanup()
    except (BridgeError, OSError, RuntimeError) as error:
        print(f"Dex update bridge stopped safely: {error}", file=sys.stderr)
        return 1
    print("Foundation delivery is complete. Once historical support is verified, future updates use /dex-update.")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
