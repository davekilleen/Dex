"""Adversarial contract for the closed historic updater bridge allow-list.

The bridge implementation exposes two deliberately small, data-only seams:

``historic_compatibility_pins()`` returns the immutable, JSON-like pin ledger
and ``historic_compatibility_for(evidence)`` returns a pin name only for a
complete *installed-source* identity.  The latter must return ``None`` for
every near miss; it is not an ancestry, version, or best-effort compatibility
detector.  Filesystem/Git collection belongs to the bridge, while this module
keeps the authorization policy independently frozen and easy to audit.

The separate existing-inputs cohort uses the equivalent
``historic_missing_migrator_pins()`` and
``historic_missing_migrator_for(evidence)`` seams.  It must not be folded into
the manifestless ledger: its policy and transition inputs already exist and
must be proven exact before the bridge can use an in-memory compatibility view.
"""

from __future__ import annotations

import hashlib
import subprocess
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from core.update import apply_update
from scripts import dex_update_bridge as bridge

# These are independent historical Git identities.  A ``None`` value is part
# of the identity: it means that the historical tree did *not* ship that
# input, not that a nearby release may supply it.
_MANIFESTLESS_MISSING_MIGRATOR = {
    "v1.20.1": {
        "tag_object": "3f7338dbe21ec98c015a3c8417d037cdd51b517d",
        "commit": "9e6f35d3282cb354008a4e7372b1cdb1d469ad3d",
        "tree": "b781bb94e417b2873d057a5a417d8c666a360bca",
        "package_blob": "524e4fc38b6ef0b266776fd52023e41e603fa4a1",
    },
    "v1.49.0": {
        "tag_object": None,
        "commit": "930adabf3e88b6534b3c90a9ad386151c1e291e4",
        "tree": "0a153375382907fd25a68d7c1845851d0d1f9946",
        "package_blob": "32c22a6a13f1444beb8ce62a30ce6309b70244be",
    },
    "v1.51.0": {
        "tag_object": None,
        "commit": "c8069c90c1715bc7a10aced19ef95e3657089bfd",
        "tree": "8129f1a2d66a6a9d412cb6a3d919af725b160e6f",
        "package_blob": "887ddacba2ff3e99b4293c50b522b112e8e7b8e0",
    },
    "v1.52.0": {
        "tag_object": None,
        "commit": "0b843163815dab2bd9d0d4797a70f7c59864e76f",
        "tree": "faebf21f5c14dc10a2ac9b28856040425e6a24a8",
        "package_blob": "34227d365e65fde32a61830c0b77cd6331fb3e7b",
    },
    "v1.53.0": {
        "tag_object": None,
        "commit": "a0bbd82d4a7c825b94c2e5467d3d34f8f2129280",
        "tree": "59a50aba122ef8213544dc99ba36fd19cc78b5c1",
        "package_blob": "d21587d1eb2e23562428fa72d4d7fb9e0a586b97",
    },
    "v1.54.0": {
        "tag_object": None,
        "commit": "3956d3710645492975d66f8f481c806c72533453",
        "tree": "ce724d55e677ef126a5f1ed4aa03f48236379327",
        "package_blob": "113903345c57bf43ad4c2f991af866f0e1183da9",
    },
    "v1.55.0": {
        "tag_object": None,
        "commit": "a023581a86b56ef97577513092001ea565832e17",
        "tree": "754789c0721bcb9bd82f43055afa8f09be0fda28",
        "package_blob": "2b1c2330ad98ca6ca85fb3319a59d7b6835f8368",
    },
    "v1.56.0": {
        "tag_object": None,
        "commit": "69505741999ab493f4f23733e33a9ffb2395c4bf",
        "tree": "255083281de057f9dd07bdfe2c3e94be1e1de5ce",
        "package_blob": "90bbdde25254fd3a9ceb3c4221337d9b3b39008f",
    },
    "v1.57.0": {
        "tag_object": None,
        "commit": "e5220bf72689e4434697aaa06978cac31cc9d5ee",
        "tree": "68af3dbebc0cbac8699dfa6d9fecf41b11852785",
        "package_blob": "f6e66582be2bd845ebc6bdf3e7166ada6a4c0d1b",
    },
    "v1.58.0": {
        "tag_object": None,
        "commit": "b001eb4048d413e1c68213f83b2c3ca2ad818a17",
        "tree": "da2ee15b6490452d85eaf8a7fd883f92b743bea9",
        "package_blob": "d25d36733053bd92f7f6d86fae9e0a887adb0bbc",
    },
    "v1.59.0": {
        "tag_object": None,
        "commit": "f3a4413d6a1bc245250e23b4f5868953620b7237",
        "tree": "9ecb0a55dd44c16b82a06ac1a02a1ee1a872607e",
        "package_blob": "5cf1c327e9eec8c42d578c3da9bb6520f7b5fe18",
    },
    "v1.60.0": {
        "tag_object": None,
        "commit": "6c986d80280e15af26b9cc4412c4578461b916db",
        "tree": "6906f751bbb058db9bd4aee01e745459661c7131",
        "package_blob": "7bbc92cdcfc2fd023861fb30d474e129f885913a",
    },
    "v1.61.0": {
        "tag_object": None,
        "commit": "b7c74d877b2aca4cb70ab343173f444feca612d0",
        "tree": "0dda073b96be4955312445a089c625cc902738ca",
        "package_blob": "884cf4421e2c3d74a8717f707fd3ac83c4bbc8fb",
    },
}

_V175_OMISSIONS = (
    "core/customization_migration/__init__.py",
    "core/customization_migration/inventory.py",
    "core/customization_migration/model.py",
    "core/customization_migration/planning.py",
    "core/customization_migration/references.py",
    "core/customization_migration/report.py",
    "core/customization_migration/service.py",
    "core/tests/test_customization_assessment.py",
    "core/tests/test_customization_assessment_doctor.py",
    "core/tests/test_customization_assessment_planning.py",
    "core/tests/test_lifecycle_topology_migration.py",
    "docs/customization-migration-threat-model.md",
    "docs/plans/2026-07-24-customization-migration-mcp.md",
)

_NATIVE_MIGRATOR_TRANSPORT = {
    "dist/release/v1.63.0-08ce719": {
        "tag_object": "492b56c53dbe469dcac93c7d9a85081026f04132",
        "commit": "08ce719d595809808e202fa4a7a5fbc68c1b5257",
        "tree": "87467beec1c11e91ff1bc27223d310b32b9b4978",
    },
    "dist/release/v1.63.0-2f006c9": {
        "tag_object": "25e579ea946e8b493fcec0d2e49aec5cdb9c1141",
        "commit": "2f006c95adcb566ee6ce881ffb534628ade49d02",
        "tree": "cfe29096d001d08ba77a9a649c9999d40f250c6e",
    },
    "dist/release/v1.63.0-9a0660f": {
        "tag_object": "d5123c4438c97b5c0e630dddad049f66389d3bc7",
        "commit": "9a0660f785b4f6d0c15ab3a77b346bb522e80eb7",
        "tree": "d4bc25fed1798db4e362506b60627da4b4fa97ad",
    },
    "dist/release/v1.63.0-9dc6e3d": {
        "tag_object": "05553ca6f04a2b89a3efbbea9d4901c63b74ae1f",
        "commit": "9dc6e3dfafd75b23c40607171787bd028099f6d1",
        "tree": "582bef8eebf62d171c63354b5cf4c618f2ac5593",
    },
}

_V161_RETIRED_MANIFEST_RELEASE = bridge.HistoricReleasePin(
    "dist/release/v1.61.0-774437a",
    "d1325426421fc0228865b2a64c8e780f2b8056ed",
    "tag",
    "774437aadfdb85bf834e2c2e1eacca6488364c18",
    "c3a71ece867e43c88dd30b8166c6087da2b344f2",
    "1.61.0",
    "b5e268bfd8bfe62e3efbe5a141e8dbb020d73609",
    "20d095aedcad0a13bd6b25ea183afcd5d367c438adb082b1044c582fb5c2ebf9",
)

_COMMON_NATIVE_MIGRATOR = {
    "package_blob": "036655ee0687f89a309b6ac18e763996e719695c",
    "policy_blob": "b2dfd209e83ecfed1d1f7fcc90be4e3444f08b2e",
    "transition_blob": "91069155a2b5d14409d927af8708556f424740bd",
    "migrator_blob": "57da3fa834ed1f9069f0187dd19b3e3e6f5b5580",
    "install_blob": "f1ce82fa657786a3b9cae0526a8a8757531f6f39",
}


# This is intentionally a *separate* failure class from the 13 manifestless
# semantic releases above.  These are the precise 13 historic installations
# that retained policy + transition inputs but not the topology migrator.  The
# table comes from the sealed 170-case breadth summary and the production
# bridge's closed ``MissingMigratorPin`` tuples.  A release must match its own
# release identity *and* its own existing-input tuple; no tuple is a generic
# migration permission.
_MISSING_MIGRATOR_FAILURES = (
    (
        "dist/release/v1.61.0-03c33d3",
        "b278bc51278c5b141dd65883fec920c8cb92d17a",
        "03c33d3c956557d1077ae2606168732a2c05bfb0",
        "f4e950f8266bd770ff99ce59f4b0de02ae8f2e19",
        "1.61.0",
        "b5e268bfd8bfe62e3efbe5a141e8dbb020d73609",
        "20d095aedcad0a13bd6b25ea183afcd5d367c438adb082b1044c582fb5c2ebf9",
        "35fa3d86020fe7b22768c199379508ddb4cef992",
        "4d7d0b4940afd1e0b0891801f75db2dce925ea6893cde82176aa0abe5b4c1872",
        "f76bf2a54600dd4ee8553664c9b9f36c4111e489",
        "f7073cf418c2ea7504f2bf1030d84d5a85be1b90f42f14895959e8318ff34e4e",
    ),
    (
        "dist/release/v1.61.0-a010533", "6ecc9ea45be51d6040466072eeedef9a26dda15f",
        "a010533278912f092e6920447846f2c7b3402abe", "3cd446661d70a9f2bc5f9fcd58083efbd2f4b436",
        "1.61.0", "b5e268bfd8bfe62e3efbe5a141e8dbb020d73609",
        "20d095aedcad0a13bd6b25ea183afcd5d367c438adb082b1044c582fb5c2ebf9",
        "35fa3d86020fe7b22768c199379508ddb4cef992",
        "4d7d0b4940afd1e0b0891801f75db2dce925ea6893cde82176aa0abe5b4c1872",
        "f76bf2a54600dd4ee8553664c9b9f36c4111e489",
        "f7073cf418c2ea7504f2bf1030d84d5a85be1b90f42f14895959e8318ff34e4e",
    ),
    (
        "dist/release/v1.61.0-dc7d332", "113ea147d484da0c2eb3bd80e35fa934388b095e",
        "dc7d332bed63589982664eca493da925cd1da6ce", "75f5fd9ae7baa05ee775093661e258746a18b0fb",
        "1.61.0", "b5e268bfd8bfe62e3efbe5a141e8dbb020d73609",
        "20d095aedcad0a13bd6b25ea183afcd5d367c438adb082b1044c582fb5c2ebf9",
        "35fa3d86020fe7b22768c199379508ddb4cef992",
        "4d7d0b4940afd1e0b0891801f75db2dce925ea6893cde82176aa0abe5b4c1872",
        "f76bf2a54600dd4ee8553664c9b9f36c4111e489",
        "f7073cf418c2ea7504f2bf1030d84d5a85be1b90f42f14895959e8318ff34e4e",
    ),
    (
        "dist/release/v1.62.0-5a4fc2a", "e031be627ae35606770cee498f1101f050e75ef6",
        "5a4fc2a5a00f8523c231d840cbe9b2decb9b101e", "d51076f79dfac62020f83fa9430defe2ca605201",
        "1.62.0", "eefff9e671693d8eba2a1bb97a4f146923542ddf",
        "0d9912852060bae981c74dff56d24d1b12cdc5125a73b2c4c87d61bf51c787a4",
        "35fa3d86020fe7b22768c199379508ddb4cef992",
        "4d7d0b4940afd1e0b0891801f75db2dce925ea6893cde82176aa0abe5b4c1872",
        "f76bf2a54600dd4ee8553664c9b9f36c4111e489",
        "f7073cf418c2ea7504f2bf1030d84d5a85be1b90f42f14895959e8318ff34e4e",
    ),
    (
        "dist/release/v1.62.0-6de410c", "5e954b3e10e52a48024b6030d3125d35d4699fb3",
        "6de410cce1b7bb80a4195940092bd5e82d7c32cf", "c0d5374d8e0494df461f012458b937fae797d007",
        "1.62.0", "eefff9e671693d8eba2a1bb97a4f146923542ddf",
        "0d9912852060bae981c74dff56d24d1b12cdc5125a73b2c4c87d61bf51c787a4",
        "35fa3d86020fe7b22768c199379508ddb4cef992",
        "4d7d0b4940afd1e0b0891801f75db2dce925ea6893cde82176aa0abe5b4c1872",
        "f76bf2a54600dd4ee8553664c9b9f36c4111e489",
        "f7073cf418c2ea7504f2bf1030d84d5a85be1b90f42f14895959e8318ff34e4e",
    ),
    (
        "dist/release/v1.62.0-ba4862f", "7157ae8defde2e8698e5b6900bf4c6d9394b16d3",
        "ba4862f55813d34ab7ec6970507dc40e3ef8027f", "235168077df9621db3fcddfb677633bdcc946723",
        "1.62.0", "eefff9e671693d8eba2a1bb97a4f146923542ddf",
        "0d9912852060bae981c74dff56d24d1b12cdc5125a73b2c4c87d61bf51c787a4",
        "35fa3d86020fe7b22768c199379508ddb4cef992",
        "4d7d0b4940afd1e0b0891801f75db2dce925ea6893cde82176aa0abe5b4c1872",
        "f76bf2a54600dd4ee8553664c9b9f36c4111e489",
        "f7073cf418c2ea7504f2bf1030d84d5a85be1b90f42f14895959e8318ff34e4e",
    ),
    (
        "dist/release/v1.62.0-cebe07b", "6b5f8f663c08613d5c8c49308bc1d08326e02a8f",
        "cebe07b23d6ceabf286ad31a24ce1aed23321c29", "4ec6aad8d9d162ccc489fbf7a9ff4b37f3e83b95",
        "1.62.0", "eefff9e671693d8eba2a1bb97a4f146923542ddf",
        "0d9912852060bae981c74dff56d24d1b12cdc5125a73b2c4c87d61bf51c787a4",
        "35fa3d86020fe7b22768c199379508ddb4cef992",
        "4d7d0b4940afd1e0b0891801f75db2dce925ea6893cde82176aa0abe5b4c1872",
        "f76bf2a54600dd4ee8553664c9b9f36c4111e489",
        "f7073cf418c2ea7504f2bf1030d84d5a85be1b90f42f14895959e8318ff34e4e",
    ),
    (
        "dist/release/v1.62.0-d1ff64c", "ff0cd2c781a9689e26b0ba207e408649bf02fff1",
        "d1ff64c7f8938cb81b548bc7238c4cc9dc398a64", "feba9f46177dd802b698d5acd60896282b1508ff",
        "1.62.0", "eefff9e671693d8eba2a1bb97a4f146923542ddf",
        "0d9912852060bae981c74dff56d24d1b12cdc5125a73b2c4c87d61bf51c787a4",
        "35fa3d86020fe7b22768c199379508ddb4cef992",
        "4d7d0b4940afd1e0b0891801f75db2dce925ea6893cde82176aa0abe5b4c1872",
        "f76bf2a54600dd4ee8553664c9b9f36c4111e489",
        "f7073cf418c2ea7504f2bf1030d84d5a85be1b90f42f14895959e8318ff34e4e",
    ),
    (
        "dist/release/v1.62.0-d5bd522", "2abdc01c6a78b1a69eb7484dae151f646c603adc",
        "d5bd522bccc3d17498d3c0c1e437ca0909c975a4", "3de9d2ec9884d4c97c471ecbf32236572fb8d496",
        "1.62.0", "eefff9e671693d8eba2a1bb97a4f146923542ddf",
        "0d9912852060bae981c74dff56d24d1b12cdc5125a73b2c4c87d61bf51c787a4",
        "b2dfd209e83ecfed1d1f7fcc90be4e3444f08b2e",
        "caf6c54e8172ecc3d8f92a13fb6a739dddb8e9965e24bfa5a6e29d08f412aa5d",
        "8cec307895b102363a85992f5f3f5a2c7b0d3730",
        "31f90404e5898913b14d61a470489ac307abfd6877e313d2d714e2204b3037f7",
    ),
    (
        "dist/release/v1.63.0-6167d6e", "041d65c0e5706b191eea172fbe59762f66cbf3c9",
        "6167d6ef82d1607ed65b7b795538eb4ccdb23cbe", "c3e961ac5cbef45d762962ecd50b4fafbdece958",
        "1.63.0", "036655ee0687f89a309b6ac18e763996e719695c",
        "c7d1e58bfcf635af6703dc519546b12ed7538a34ee298d493b3db373cb495c98",
        "b2dfd209e83ecfed1d1f7fcc90be4e3444f08b2e",
        "caf6c54e8172ecc3d8f92a13fb6a739dddb8e9965e24bfa5a6e29d08f412aa5d",
        "91069155a2b5d14409d927af8708556f424740bd",
        "afd7f6338561ecd3597f32552e594f14630028f9ced64755f6dc11249b43d7a4",
    ),
    (
        "dist/release/v1.63.0-d1050f4", "d4a49d6be2e5bdccf6ceee3cc6f016524e4d02bc",
        "d1050f47598a1625205dc571313dc3d4d08cfcd3", "b18cee1e7f61d4873c0748bd48396d7aa9ccd985",
        "1.63.0", "036655ee0687f89a309b6ac18e763996e719695c",
        "c7d1e58bfcf635af6703dc519546b12ed7538a34ee298d493b3db373cb495c98",
        "b2dfd209e83ecfed1d1f7fcc90be4e3444f08b2e",
        "caf6c54e8172ecc3d8f92a13fb6a739dddb8e9965e24bfa5a6e29d08f412aa5d",
        "cffb865aafcda0d20e66082f9c5eab4323f7b664",
        "d4fe097c6be47b5ca6198fbca412959c9777da2e6cafb863235be73c71a376a9",
    ),
    (
        "v1.62.0", "4913a778452003fcf8dc71a10222d5275ff28d5c",
        "77c4a15a7884080e48b095c8de2c384d01a87883", "1bf30a86c151890024040f0e4e1a533be17c5686",
        "1.62.0", "2d7f21a72798d4189f042e955e62ee799e90a90c",
        "75bef63d563a7e5062db6ad664ccb65a7581dbfd3d466655d1b3709bbad7ffa5",
        "35fa3d86020fe7b22768c199379508ddb4cef992",
        "4d7d0b4940afd1e0b0891801f75db2dce925ea6893cde82176aa0abe5b4c1872",
        "f76bf2a54600dd4ee8553664c9b9f36c4111e489",
        "f7073cf418c2ea7504f2bf1030d84d5a85be1b90f42f14895959e8318ff34e4e",
    ),
    (
        "v1.63.0", "eff2f060455f186fcd27f5e680825051baf037b7",
        "b5ee55366f3600b79748a9b56e063a9825172a45", "a418102a6d8254a14c81575d1d86aea7d28bd6f8",
        "1.63.0", "846e23a1dd09c7096784268b234fde7139915575",
        "2f13e9f4f765dbe18a68a6fbe4b58f211eccecd50deba60e45647fdef0b9f6cf",
        "b2dfd209e83ecfed1d1f7fcc90be4e3444f08b2e",
        "caf6c54e8172ecc3d8f92a13fb6a739dddb8e9965e24bfa5a6e29d08f412aa5d",
        "cffb865aafcda0d20e66082f9c5eab4323f7b664",
        "d4fe097c6be47b5ca6198fbca412959c9777da2e6cafb863235be73c71a376a9",
    ),
)


def _missing_migrator_ledger() -> dict[str, dict[str, object]]:
    """Independent expected public seam for exact existing-input authorizations."""

    fields = (
        "tag",
        "tag_object",
        "commit",
        "tree",
        "version",
        "package_blob",
        "package_sha256",
        "policy_blob",
        "policy_sha256",
        "transition_blob",
        "transition_sha256",
    )
    return {
        values[0]: {
            "kind": "existing-inputs-missing-migrator",
            "role": "installed-source",
            **dict(zip(fields, values, strict=True)),
            "migrator_blob": None,
            "migrator_state": "absent",
            "overwrite_existing_inputs": False,
        }
        for values in _MISSING_MIGRATOR_FAILURES
    }


def _expected_pins() -> dict[str, dict[str, object]]:
    pins: dict[str, dict[str, object]] = {}
    for tag, identity in _MANIFESTLESS_MISSING_MIGRATOR.items():
        pins[tag] = {
            "kind": "manifestless-missing-migrator",
            "role": "installed-source",
            "tag": tag,
            **identity,
            "manifest_blob": None,
            "policy_blob": None,
            "transition_blob": None,
            "migrator_blob": None,
            "unexpected_nonregular_paths": (),
        }
    pins["v1.20.1"].update(
        {
            "shipped_symlink": {
                "path": ".pi/agent/extensions/dex",
                "blob": "f1c88c92cea996705f982e902bafb758156aef52",
                "target": "../../../pi-extensions/dex",
            },
        }
    )
    pins["dist/release/v1.61.0-774437a"] = {
        "kind": "complete-manifest-retired-paths",
        "role": "installed-source",
        "tag": "dist/release/v1.61.0-774437a",
        "tag_object": "d1325426421fc0228865b2a64c8e780f2b8056ed",
        "commit": "774437aadfdb85bf834e2c2e1eacca6488364c18",
        "tree": "c3a71ece867e43c88dd30b8166c6087da2b344f2",
        "version": "1.61.0",
        "package_blob": "b5e268bfd8bfe62e3efbe5a141e8dbb020d73609",
        "package_sha256": "20d095aedcad0a13bd6b25ea183afcd5d367c438adb082b1044c582fb5c2ebf9",
        "manifest_blob": "feef2bb3dd6756c7c54d76bdfd6128904c87f679",
        "manifest_sha256": "edf6e98bc16063c47b362280cfa33fd10f075a5d240d5884d5ded5d894cbcc63",
        "manifest_path_count": 768,
        "policy_blob": None,
        "transition_blob": None,
        "migrator_blob": None,
        "omission_identities": (
            "50a3e65dc2d65e6f6b28b30b630e06656d95ddd82f4a68a7152017119b110f90",
            "af78f3d480b78b5bb558d873b98638c91d532de98f84f8f50e73448a1404b37d",
        ),
        "unexpected_nonregular_paths": (),
    }
    pins["v1.75.0"] = {
        "kind": "incomplete-manifest",
        "role": "installed-source",
        "tag": "v1.75.0",
        "tag_object": None,
        "commit": "5e73481519ee9b5fe9a6c3196ee7cabaa0446ee8",
        "tree": "382b92df5b3a14da90e9122956353f589f2fc0b7",
        "package_blob": "1cacd5c174cfc309e855bd54ae96bcf04afa4079",
        "manifest_blob": "6d2105eb1e33bd007ef8b4e2e77b927508a150f7",
        "manifest_sha256": "6a065ef3bcce45ac8e42d8143a4eb9e3516ea633fd0cbe8c3d2aff10a137ec34",
        "manifest_path_count": 1201,
        "omitted_paths": _V175_OMISSIONS,
        "omitted_paths_sha256": "b476b6a35ac869339e93f6451f13f6a09c6622b7be6ba73ee6e82bc404cc567d",
        "policy_blob": "b2dfd209e83ecfed1d1f7fcc90be4e3444f08b2e",
        "transition_blob": "2a016eafa4f2712343c3eea206b5be22259e3362",
        "migrator_blob": "559a870762bd8feb68aac7b6a9f93ec2f99d1efd",
        "unexpected_nonregular_paths": (),
    }
    pins["v1.81.0"] = {
        "kind": "semantic-no-catalog",
        "role": "installed-source",
        "tag": "v1.81.0",
        "tag_object": None,
        "commit": "0f23787a22aa52afb40878df05e4819f77d179e6",
        "tree": "03e1832add6a27bc6c6dc833bfdba2b6cf7fd524",
        "package_blob": "f54091ab0c0d543c848bb1344b8a0048c067b89f",
        "catalog_blob": None,
        "manifest_blob": "1264aba3b8f1cff516caeb277380c09be1973e99",
        "manifest_sha256": "fdd28af603f7575efcfe358472a60d0513b08d2f0f7aecf8395f7a0da27ea8ca",
        "manifest_path_count": 1297,
        "policy_blob": "7d1f2b3ace56e12fce2ff01fafe6435cd1b59e59",
        "transition_blob": "4b7ad8ff59d95a5e0af7106cb40f3aafa699400c",
        "migrator_blob": "c73fe7e186abbcd8dc588fa5c94d6244bf156662",
        "unexpected_nonregular_paths": (),
    }
    for tag, identity in _NATIVE_MIGRATOR_TRANSPORT.items():
        pins[tag] = {
            "kind": "native-migrator-file-transport",
            "role": "installed-source",
            "tag": tag,
            **identity,
            **_COMMON_NATIVE_MIGRATOR,
            "unexpected_nonregular_paths": (),
        }
    return pins


def _ledger() -> dict[str, dict[str, object]]:
    """Normalize the bridge's read-only ledger without sharing test objects."""

    return {name: dict(pin) for name, pin in bridge.historic_compatibility_pins().items()}


def _authorize(evidence: dict[str, object]) -> str | None:
    return bridge.historic_compatibility_for(evidence)


def _missing_migrator_pins() -> dict[str, dict[str, object]]:
    return {
        name: dict(pin)
        for name, pin in bridge.historic_missing_migrator_pins().items()
    }


def _authorize_missing_migrator(evidence: dict[str, object]) -> str | None:
    return bridge.historic_missing_migrator_for(evidence)


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Dex Updater Test",
            "-c",
            "user.email=updater-test@example.com",
            "-C",
            str(repository),
            *arguments,
        ],
        check=True,
        capture_output=True,
    )
    return completed.stdout.decode("utf-8").strip()


def _historic_checkout(tmp_path: Path, pin: bridge.HistoricReleasePin) -> Path:
    """Make a disposable checkout backed by the test runner's real Git objects."""

    repository = tmp_path / "historic-vault"
    subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--shared",
            "--no-checkout",
            str(Path(__file__).resolve().parents[2]),
            str(repository),
        ],
        check=True,
    )
    _git(repository, "checkout", "--quiet", "--detach", pin.commit)
    _git(repository, "update-ref", f"refs/tags/{pin.tag}", pin.tag_object)
    return repository


def _restore_checkout(repository: Path, pin: bridge.HistoricReleasePin) -> None:
    _git(repository, "checkout", "--quiet", "--detach", "--force", pin.commit)
    _git(repository, "clean", "-dffx")
    _git(repository, "update-ref", f"refs/tags/{pin.tag}", pin.tag_object)


def _delivery_adapter(
    tmp_path: Path,
    repository: Path,
) -> tuple[bridge._FoundationLifecycleService, object]:
    source = tmp_path / "foundation-source"
    migrator = source / bridge._TOPOLOGY_MIGRATOR_RELATIVE
    migrator.parent.mkdir(parents=True)
    migrator.write_text("'use strict';\n", encoding="utf-8")

    engine = ModuleType("historic_delivery_engine")
    engine.TOPOLOGY_MIGRATOR_RELATIVE = bridge._TOPOLOGY_MIGRATOR_RELATIVE
    engine.topology_state = lambda _root: "invalid-combined"
    engine._migrator_command = lambda _root, _mode: []

    class DeliveryService:
        commit = ""

        def build_and_preview_delivered_release(self, _vault_root: Path, _release: object):
            entries = apply_update._tree_entries(repository, repository / ".git", self.commit)
            apply_update._verify_manifest(repository, repository / ".git", entries)
            for entry in entries:
                apply_update.portable_contract.resolve(entry.path)
            return entries

    service = DeliveryService()
    return bridge._FoundationLifecycleService(service, engine, apply_update, source), service


def _topology_command_adapter(
    tmp_path: Path,
) -> tuple[bridge._FoundationLifecycleService, ModuleType]:
    """Build the real bridge command adapter around a disposable migrator."""

    source = tmp_path / "foundation-topology-source"
    migrator = source / bridge._TOPOLOGY_MIGRATOR_RELATIVE
    migrator.parent.mkdir(parents=True)
    migrator.write_text(
        """'use strict';
const fs = require('node:fs');
const path = require('node:path');
fs.readFileSync(path.join(process.cwd(), 'core/migrations/tracked-ignored-policy.yaml'));
fs.readFileSync(path.join(process.cwd(), 'System/.local-only-preservation-transition.json'));
""",
        encoding="utf-8",
    )

    engine = ModuleType("historic_topology_engine")
    engine.TOPOLOGY_MIGRATOR_RELATIVE = bridge._TOPOLOGY_MIGRATOR_RELATIVE
    engine.topology_state = lambda _root: "invalid-combined"

    def rejected_command(_root: Path, _mode: str) -> list[str]:
        raise RuntimeError("historic vault migrator was rejected")

    engine._migrator_command = rejected_command

    class TopologyService:
        pass

    return (
        bridge._FoundationLifecycleService(
            TopologyService(),
            engine,
            apply_update,
            source,
        ),
        engine,
    )


def _commit_nonregular_variant(repository: Path, base: str, mode: str, name: str) -> tuple[str, str]:
    _git(repository, "checkout", "--quiet", "--detach", "--force", base)
    if mode == "120000":
        target = repository / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to("CLAUDE.md")
        _git(repository, "add", "--", name)
    else:
        _git(repository, "update-index", "--add", "--cacheinfo", f"160000,{base},{name}")
    _git(repository, "commit", "--quiet", "-m", f"test {mode} entry")
    commit = _git(repository, "rev-parse", "HEAD^{commit}")
    return commit, _git(repository, "rev-parse", "HEAD^{tree}")


def _commit_manifestless_omission_variant(
    repository: Path,
    base: str,
    mutation: str,
) -> tuple[str, str]:
    """Create one real Git near-miss around the closed legacy omission pair."""

    readme = "extensions/tau-mirror/README-TAU-MIRROR.md"
    unexpected = "extensions/tau-mirror/unexpected.md"
    _git(repository, "checkout", "--quiet", "--detach", "--force", base)
    if mutation == "missing":
        _git(repository, "rm", "--quiet", "--", readme)
    elif mutation == "extra":
        blob = _git(repository, "rev-parse", f"{base}:{readme}")
        _git(
            repository,
            "update-index",
            "--add",
            "--cacheinfo",
            f"100644,{blob},{unexpected}",
        )
    elif mutation == "tampered-blob":
        (repository / readme).write_text("tampered historic bytes\n", encoding="utf-8")
        _git(repository, "add", "--", readme)
    elif mutation == "altered-mode":
        _git(repository, "update-index", "--chmod=+x", "--", readme)
    elif mutation == "renamed-path":
        _git(repository, "mv", "--", readme, unexpected)
    else:  # pragma: no cover - the parametrization below is deliberately closed
        raise AssertionError(f"unknown test mutation: {mutation}")
    _git(
        repository,
        "commit",
        "--quiet",
        "-m",
        f"test manifestless omission {mutation}",
    )
    commit = _git(repository, "rev-parse", "HEAD^{commit}")
    return commit, _git(repository, "rev-parse", "HEAD^{tree}")


def _commit_retired_manifest_variant(
    repository: Path,
    base: str,
    mutation: str,
) -> tuple[str, str, str, str]:
    """Create a manifest-consistent real Git near-miss around the retired pair."""

    readme = "extensions/tau-mirror/README-TAU-MIRROR.md"
    unexpected = "extensions/tau-mirror/unexpected.md"
    manifest = repository / "System/.installed-files.manifest"
    _git(repository, "checkout", "--quiet", "--detach", "--force", base)
    paths = manifest.read_text(encoding="utf-8").splitlines()
    if mutation == "missing":
        _git(repository, "rm", "--quiet", "--", readme)
        paths.remove(readme)
    elif mutation == "extra":
        target = repository / unexpected
        target.write_text("unexpected retired content\n", encoding="utf-8")
        _git(repository, "add", "--", unexpected)
        paths.append(unexpected)
    elif mutation == "tampered-blob":
        (repository / readme).write_text("tampered historic bytes\n", encoding="utf-8")
        _git(repository, "add", "--", readme)
    elif mutation == "altered-mode":
        _git(repository, "update-index", "--chmod=+x", "--", readme)
    elif mutation == "renamed-path":
        _git(repository, "mv", "--", readme, unexpected)
        paths[paths.index(readme)] = unexpected
    else:  # pragma: no cover - the parametrization below is deliberately closed
        raise AssertionError(f"unknown test mutation: {mutation}")
    if mutation in {"missing", "extra", "renamed-path"}:
        manifest.write_text("\n".join(sorted(paths)) + "\n", encoding="utf-8")
        _git(repository, "add", "--", "System/.installed-files.manifest")
    _git(repository, "commit", "--quiet", "-m", f"test retired manifest {mutation}")
    commit = _git(repository, "rev-parse", "HEAD^{commit}")
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    manifest_blob = _git(repository, "rev-parse", f"{commit}:System/.installed-files.manifest")
    manifest_sha256 = subprocess.run(
        ["git", "-C", str(repository), "cat-file", "blob", manifest_blob],
        check=True,
        capture_output=True,
    ).stdout
    return commit, tree, manifest_blob, hashlib.sha256(manifest_sha256).hexdigest()


def test_historic_ledger_is_exactly_the_closed_frozen_set() -> None:
    """No range, prefix, or latest-version fallback may enter this ledger."""

    assert _ledger() == _expected_pins()
    assert len(_MANIFESTLESS_MISSING_MIGRATOR) == 13
    assert len(_V175_OMISSIONS) == 13
    assert len(_NATIVE_MIGRATOR_TRANSPORT) == 4


def test_missing_migrator_ledger_is_the_exact_13_case_failure_group() -> None:
    """The old existing-inputs problem cannot grow into a version-range rule."""

    assert _missing_migrator_pins() == _missing_migrator_ledger()
    assert len(_MISSING_MIGRATOR_FAILURES) == 13


@pytest.mark.parametrize("name", tuple(_missing_migrator_ledger()))
def test_each_missing_migrator_tuple_is_authorized_only_when_complete(name: str) -> None:
    evidence = deepcopy(_missing_migrator_ledger()[name])
    assert _authorize_missing_migrator(evidence) == name


@pytest.mark.parametrize("name", tuple(_missing_migrator_ledger()))
@pytest.mark.parametrize(
    "field",
    (
        "tag",
        "tag_object",
        "commit",
        "tree",
        "version",
        "package_blob",
        "package_sha256",
        "policy_blob",
        "policy_sha256",
        "transition_blob",
        "transition_sha256",
        "migrator_blob",
        "migrator_state",
        "overwrite_existing_inputs",
        "role",
    ),
)
def test_missing_migrator_one_field_near_miss_is_refused(
    name: str,
    field: str,
) -> None:
    evidence = deepcopy(_missing_migrator_ledger()[name])
    actual = evidence[field]
    if isinstance(actual, str):
        evidence[field] = ("0" * len(actual)) if actual else "changed"
    elif actual is None:
        evidence[field] = "unexpected-present-migrator"
    elif isinstance(actual, bool):
        evidence[field] = not actual
    else:  # pragma: no cover - fixed literal table guards the supported shapes.
        raise AssertionError(f"missing-migrator test has unsupported field: {field}")

    assert _authorize_missing_migrator(evidence) is None


def test_missing_migrator_tuple_cannot_borrow_a_nearby_release_inputs() -> None:
    source = deepcopy(_missing_migrator_ledger()["dist/release/v1.62.0-d5bd522"])
    nearby = _missing_migrator_ledger()["dist/release/v1.62.0-5a4fc2a"]
    source["policy_blob"] = nearby["policy_blob"]
    source["policy_sha256"] = nearby["policy_sha256"]
    source["transition_blob"] = nearby["transition_blob"]
    source["transition_sha256"] = nearby["transition_sha256"]

    assert _authorize_missing_migrator(source) is None


@pytest.mark.parametrize("name", tuple(_expected_pins()))
def test_each_frozen_historic_identity_authorizes_only_as_installed_source(name: str) -> None:
    evidence = deepcopy(_expected_pins()[name])

    assert _authorize(evidence) == name

    modern_target = deepcopy(evidence)
    modern_target["role"] = "delivery-target"
    assert _authorize(modern_target) is None


@pytest.mark.parametrize("name", tuple(_expected_pins()))
def test_one_tampered_identity_field_never_inherits_historic_authorization(name: str) -> None:
    evidence = deepcopy(_expected_pins()[name])
    evidence["package_blob"] = "0" * 40

    assert _authorize(evidence) is None


def test_cross_pairing_a_real_tree_and_a_real_package_is_not_compatibility() -> None:
    evidence = deepcopy(_expected_pins()["v1.57.0"])
    evidence["tree"] = _expected_pins()["v1.58.0"]["tree"]

    assert _authorize(evidence) is None


@pytest.mark.parametrize(
    "field",
    tuple(_expected_pins()["dist/release/v1.61.0-774437a"]),
)
def test_retired_manifest_one_field_near_miss_is_refused(field: str) -> None:
    evidence = deepcopy(_expected_pins()["dist/release/v1.61.0-774437a"])
    actual = evidence[field]
    if isinstance(actual, str):
        evidence[field] = ("0" * len(actual)) if actual else "changed"
    elif actual is None:
        evidence[field] = "unexpected-present-input"
    elif isinstance(actual, int):
        evidence[field] = actual + 1
    elif isinstance(actual, tuple):
        evidence[field] = (("0" * 64), *actual[1:]) if actual else ("unexpected",)
    else:  # pragma: no cover - fixed literal table guards the supported shapes.
        raise AssertionError(f"retired-manifest test has unsupported field: {field}")

    assert _authorize(evidence) is None


def test_v120_tau_symlink_is_exact_and_another_symlink_is_not_allowed() -> None:
    evidence = deepcopy(_expected_pins()["v1.20.1"])
    assert _authorize(evidence) == "v1.20.1"

    evidence["shipped_symlink"] = {
        **evidence["shipped_symlink"],
        "target": "../../../../outside-the-vault",
    }
    assert _authorize(evidence) is None


def test_v120_manifestless_omission_identities_are_closed() -> None:
    evidence = deepcopy(_expected_pins()["v1.20.1"])
    assert _authorize(evidence) == "v1.20.1"

    exact = frozenset(
        {
            "af78f3d480b78b5bb558d873b98638c91d532de98f84f8f50e73448a1404b37d",
            "50a3e65dc2d65e6f6b28b30b630e06656d95ddd82f4a68a7152017119b110f90",
        }
    )
    assert bridge._manifestless_omission_identities_match(exact)

    omitted = next(iter(exact))
    tampered = frozenset((exact - {omitted}) | {"0" + omitted[1:]})
    assert not bridge._manifestless_omission_identities_match(tampered)
    assert not bridge._manifestless_omission_identities_match(exact - {omitted})
    assert not bridge._manifestless_omission_identities_match(exact | {"f" * 64})


@pytest.mark.parametrize("name", ("v1.75.0", "v1.81.0", "dist/release/v1.63.0-08ce719"))
def test_unexpected_nonregular_entry_is_not_hidden_by_a_known_historic_shape(name: str) -> None:
    evidence = deepcopy(_expected_pins()[name])
    evidence["unexpected_nonregular_paths"] = ("System/unsafe-link",)

    assert _authorize(evidence) is None


def test_missing_migrator_policy_transition_and_package_are_a_closed_tuple() -> None:
    evidence = deepcopy(_expected_pins()["v1.61.0"])
    assert _authorize(evidence) == "v1.61.0"

    # The empty historical tuple is not permission to borrow newer inputs.
    evidence["policy_blob"] = _COMMON_NATIVE_MIGRATOR["policy_blob"]
    evidence["transition_blob"] = _COMMON_NATIVE_MIGRATOR["transition_blob"]
    assert _authorize(evidence) is None


def test_native_file_transport_permission_is_not_reused_by_a_nearby_release() -> None:
    evidence = deepcopy(_expected_pins()["dist/release/v1.63.0-08ce719"])
    assert _authorize(evidence) == "dist/release/v1.63.0-08ce719"

    evidence["tag"] = "dist/release/v1.63.0-f2f288e"
    assert _authorize(evidence) is None


def test_modern_foundation_is_not_granted_any_historic_escape_hatch() -> None:
    """A current target is handled by normal validation, never this ledger."""

    assert _authorize(
        {
            "role": "delivery-target",
            "tag": bridge.FOUNDATION.tag,
            "tag_object": bridge.FOUNDATION.tag_object,
            "commit": bridge.FOUNDATION.commit,
            "tree": bridge.FOUNDATION.tree,
            "package_blob": "not-a-historic-package",
            "unexpected_nonregular_paths": (),
        }
    ) is None


def test_runtime_legacy_topology_matches_real_git_and_regular_files_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = bridge.MANIFESTLESS_SEMANTIC_RELEASES[1]
    nearby = bridge.MANIFESTLESS_SEMANTIC_RELEASES[2]
    repository = _historic_checkout(tmp_path, pin)
    impossible_fallback = replace(
        bridge.LEGACY_TOPOLOGY_FOUNDATION,
        tag="v9.9.9",
        commit="0" * 40,
        tree="0" * 40,
    )
    monkeypatch.setattr(bridge, "MANIFESTLESS_SEMANTIC_RELEASES", (pin,))
    monkeypatch.setattr(bridge, "MISSING_MIGRATOR_RELEASES", ())

    assert bridge._supported_legacy_topology(repository, impossible_fallback) is True

    mutations = (
        replace(pin, tag_object=nearby.tag_object),
        replace(pin, tag_object_type="tag"),
        replace(pin, commit=nearby.commit),
        replace(pin, tree=nearby.tree),
        replace(pin, package_blob=nearby.package_blob),
        replace(pin, package_sha256="0" * 64),
    )
    for mutation in mutations:
        monkeypatch.setattr(bridge, "MANIFESTLESS_SEMANTIC_RELEASES", (mutation,))
        assert bridge._supported_legacy_topology(repository, impossible_fallback) is False
    monkeypatch.setattr(bridge, "MANIFESTLESS_SEMANTIC_RELEASES", (pin,))

    package = repository / bridge._PACKAGE_RELATIVE
    package.write_text('{"version":"1.49.0","tampered":true}\n', encoding="utf-8")
    assert bridge._supported_legacy_topology(repository, impossible_fallback) is False

    _restore_checkout(repository, pin)
    package.unlink()
    package.symlink_to("CLAUDE.md")
    assert bridge._supported_legacy_topology(repository, impossible_fallback) is False

    _restore_checkout(repository, pin)
    package.unlink()
    package.mkdir()
    assert bridge._supported_legacy_topology(repository, impossible_fallback) is False

    _restore_checkout(repository, pin)
    _git(repository, "update-ref", f"refs/tags/{pin.tag}", nearby.commit)
    assert bridge._supported_legacy_topology(repository, impossible_fallback) is False

    _git(repository, "checkout", "--quiet", "--detach", "--force", bridge.FOUNDATION.commit)
    assert bridge._supported_legacy_topology(repository, impossible_fallback) is False


def test_runtime_legacy_topology_refuses_cross_borrowed_existing_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = bridge.MISSING_MIGRATOR_RELEASES[0]
    borrowed = bridge.MISSING_MIGRATOR_RELEASES[8]
    repository = _historic_checkout(tmp_path, pin.release)
    impossible_fallback = replace(
        bridge.LEGACY_TOPOLOGY_FOUNDATION,
        tag="v9.9.9",
        commit="0" * 40,
        tree="0" * 40,
    )
    monkeypatch.setattr(bridge, "MANIFESTLESS_SEMANTIC_RELEASES", ())
    monkeypatch.setattr(bridge, "MISSING_MIGRATOR_RELEASES", (pin,))

    assert bridge._supported_legacy_topology(repository, impossible_fallback) is True

    for relative, blob in (
        (bridge._TRACKED_IGNORE_POLICY_RELATIVE, borrowed.inputs.policy_blob),
        (bridge._PRESERVATION_TRANSITION_RELATIVE, borrowed.inputs.transition_blob),
    ):
        (repository / relative).write_bytes(
            subprocess.run(
                ["git", "-C", str(repository), "cat-file", "blob", blob],
                check=True,
                capture_output=True,
            ).stdout
        )

    assert bridge._supported_legacy_topology(repository, impossible_fallback) is False


def test_runtime_legacy_command_reproves_unchanged_existing_input_tuple(
    tmp_path: Path,
) -> None:
    pin = bridge.MISSING_MIGRATOR_RELEASES[3]
    repository = _historic_checkout(tmp_path, pin.release)
    adapter, engine = _topology_command_adapter(tmp_path)

    with adapter._topology_source():
        assert engine.topology_state(repository) == "combined"
        command = engine._migrator_command(repository, "--dry-run")

    assert command[-2:] == [str(adapter._migrator), "--dry-run"]
    completed = subprocess.run(
        command,
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        env=bridge._bridge_environment(),
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("mode", ("--dry-run", "--auto"))
def test_runtime_legacy_command_refuses_exact_cross_borrow_after_authorization(
    tmp_path: Path,
    mode: str,
) -> None:
    pin = bridge.MISSING_MIGRATOR_RELEASES[3]
    borrowed = bridge.MISSING_MIGRATOR_RELEASES[8]
    assert pin.release.version == borrowed.release.version
    assert pin.release.package_blob == borrowed.release.package_blob
    assert pin.inputs != borrowed.inputs

    repository = _historic_checkout(tmp_path, pin.release)
    adapter, engine = _topology_command_adapter(tmp_path)

    with adapter._topology_source():
        assert engine.topology_state(repository) == "combined"
        for relative, blob in (
            (bridge._TRACKED_IGNORE_POLICY_RELATIVE, borrowed.inputs.policy_blob),
            (bridge._PRESERVATION_TRANSITION_RELATIVE, borrowed.inputs.transition_blob),
        ):
            (repository / relative).write_bytes(
                subprocess.run(
                    ["git", "-C", str(repository), "cat-file", "blob", blob],
                    check=True,
                    capture_output=True,
                ).stdout
            )

        with pytest.raises(bridge.BridgeError, match="identity changed after authorization"):
            engine._migrator_command(repository, mode)


def test_runtime_legacy_command_refuses_existing_inputs_added_to_absent_class(
    tmp_path: Path,
) -> None:
    pin = bridge.MANIFESTLESS_SEMANTIC_RELEASES[1]
    borrowed = bridge.MISSING_MIGRATOR_RELEASES[8]
    repository = _historic_checkout(tmp_path, pin)
    adapter, engine = _topology_command_adapter(tmp_path)

    with adapter._topology_source():
        assert engine.topology_state(repository) == "combined"
        for relative, blob in (
            (bridge._TRACKED_IGNORE_POLICY_RELATIVE, borrowed.inputs.policy_blob),
            (bridge._PRESERVATION_TRANSITION_RELATIVE, borrowed.inputs.transition_blob),
        ):
            candidate = repository / relative
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(
                subprocess.run(
                    ["git", "-C", str(repository), "cat-file", "blob", blob],
                    check=True,
                    capture_output=True,
                ).stdout
            )

        with pytest.raises(bridge.BridgeError, match="identity changed after authorization"):
            engine._migrator_command(repository, "--dry-run")


def test_bound_legacy_preload_refuses_cross_borrow_after_command_creation(
    tmp_path: Path,
) -> None:
    pin = bridge.MISSING_MIGRATOR_RELEASES[3]
    borrowed = bridge.MISSING_MIGRATOR_RELEASES[8]
    repository = _historic_checkout(tmp_path, pin.release)
    adapter, engine = _topology_command_adapter(tmp_path)

    with adapter._topology_source():
        assert engine.topology_state(repository) == "combined"
        command = engine._migrator_command(repository, "--dry-run")

    for relative, blob in (
        (bridge._TRACKED_IGNORE_POLICY_RELATIVE, borrowed.inputs.policy_blob),
        (bridge._PRESERVATION_TRANSITION_RELATIVE, borrowed.inputs.transition_blob),
    ):
        (repository / relative).write_bytes(
            subprocess.run(
                ["git", "-C", str(repository), "cat-file", "blob", blob],
                check=True,
                capture_output=True,
            ).stdout
        )

    completed = subprocess.run(
        command,
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        env=bridge._bridge_environment(),
    )
    assert completed.returncode != 0
    assert "refused an unknown legacy compatibility tuple" in completed.stderr


def test_runtime_retired_manifest_topology_requires_exact_git_and_absent_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = bridge.V161_RETIRED_MANIFEST_RELEASE
    nearby = bridge.MANIFESTLESS_SEMANTIC_RELEASES[-1]
    repository = _historic_checkout(tmp_path, pin)
    impossible_fallback = replace(
        bridge.LEGACY_TOPOLOGY_FOUNDATION,
        tag="v9.9.9",
        commit="0" * 40,
        tree="0" * 40,
    )
    monkeypatch.setattr(bridge, "MANIFESTLESS_SEMANTIC_RELEASES", ())
    monkeypatch.setattr(bridge, "MISSING_MIGRATOR_RELEASES", ())

    assert bridge._supported_legacy_topology(repository, impossible_fallback) is True

    mutations = (
        replace(pin, tag_object=nearby.tag_object),
        replace(pin, tag_object_type="commit"),
        replace(pin, commit=nearby.commit),
        replace(pin, tree=nearby.tree),
        replace(pin, package_blob=nearby.package_blob),
        replace(pin, package_sha256="0" * 64),
    )
    for mutation in mutations:
        monkeypatch.setattr(bridge, "V161_RETIRED_MANIFEST_RELEASE", mutation)
        assert bridge._supported_legacy_topology(repository, impossible_fallback) is False
    monkeypatch.setattr(bridge, "V161_RETIRED_MANIFEST_RELEASE", pin)

    absent_inputs = (
        bridge._TRACKED_IGNORE_POLICY_RELATIVE,
        bridge._PRESERVATION_TRANSITION_RELATIVE,
        bridge._TOPOLOGY_MIGRATOR_RELATIVE,
    )
    for relative in absent_inputs:
        candidate = repository / relative
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text("unexpected compatibility input\n", encoding="utf-8")
        assert bridge._supported_legacy_topology(repository, impossible_fallback) is False
        candidate.unlink()

    symlink = repository / bridge._TRACKED_IGNORE_POLICY_RELATIVE
    symlink.symlink_to(repository / "CLAUDE.md")
    assert bridge._supported_legacy_topology(repository, impossible_fallback) is False

    _restore_checkout(repository, pin)
    _git(repository, "update-ref", f"refs/tags/{pin.tag}", nearby.commit)
    assert bridge._supported_legacy_topology(repository, impossible_fallback) is False

    _restore_checkout(repository, pin)
    _git(repository, "checkout", "--quiet", "--detach", "--force", bridge.FOUNDATION.commit)
    assert bridge._supported_legacy_topology(repository, impossible_fallback) is False


def test_runtime_native_transport_matches_only_exact_git_and_regular_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = bridge.NATIVE_MIGRATOR_TRANSPORT_RELEASES[0]
    nearby = bridge.NATIVE_MIGRATOR_TRANSPORT_RELEASES[1]
    repository = _historic_checkout(tmp_path, pin)

    assert bridge._native_transport_release(repository) == pin
    monkeypatch.setattr(bridge, "NATIVE_MIGRATOR_TRANSPORT_RELEASES", (pin,))

    package = repository / bridge._PACKAGE_RELATIVE
    package.write_text('{"version":"1.63.0","tampered":true}\n', encoding="utf-8")
    assert bridge._native_transport_release(repository) is None

    _restore_checkout(repository, pin)
    candidate = repository / bridge._TOPOLOGY_MIGRATOR_RELATIVE
    candidate.unlink()
    candidate.symlink_to(repository / "CLAUDE.md")
    assert bridge._native_transport_release(repository) is None

    _restore_checkout(repository, pin)
    candidate = repository / bridge._TRACKED_IGNORE_POLICY_RELATIVE
    candidate.unlink()
    candidate.mkdir()
    assert bridge._native_transport_release(repository) is None

    _restore_checkout(repository, pin)
    _git(repository, "update-ref", f"refs/tags/{pin.tag}", nearby.tag_object)
    assert bridge._native_transport_release(repository) is None

    _git(repository, "checkout", "--quiet", "--detach", "--force", bridge.FOUNDATION.commit)
    assert bridge._native_transport_release(repository) is None


def test_runtime_manifest_omission_adapter_accepts_only_exact_historic_trees(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifestless = bridge.MANIFESTLESS_SEMANTIC_RELEASES[0]
    repository = _historic_checkout(tmp_path, manifestless)
    adapter, service = _delivery_adapter(tmp_path, repository)

    service.commit = manifestless.commit
    _git(repository, "update-ref", "refs/dex/installed", manifestless.commit)
    entries = adapter.build_and_preview_delivered_release(repository, {})
    assert bridge._LEGACY_SHIPPED_SYMLINK_RELATIVE.as_posix() not in {
        entry.path for entry in entries
    }
    assert "System/.installed-files.manifest" not in {entry.path for entry in entries}

    defective = bridge.V175_DEFECTIVE_MANIFEST_RELEASE
    _restore_checkout(repository, defective)
    service.commit = defective.commit
    _git(repository, "update-ref", "refs/dex/installed", defective.commit)
    entries = adapter.build_and_preview_delivered_release(repository, {})
    paths = {entry.path for entry in entries}
    assert len(entries) == 1201
    assert paths.isdisjoint(bridge._V175_DEFECTIVE_MANIFEST_OMISSIONS)

    changed = dict(bridge._V175_DEFECTIVE_MANIFEST_OMISSIONS)
    changed[next(iter(changed))] = "0" * 40
    monkeypatch.setattr(bridge, "_V175_DEFECTIVE_MANIFEST_OMISSIONS", changed)
    with pytest.raises(apply_update.ReleaseVerificationError, match="omission changed"):
        adapter.build_and_preview_delivered_release(repository, {})


def test_runtime_retired_manifest_adapter_accepts_exact_public_git_tree(
    tmp_path: Path,
) -> None:
    pin = _V161_RETIRED_MANIFEST_RELEASE
    repository = _historic_checkout(tmp_path, pin)
    impossible_fallback = replace(
        bridge.LEGACY_TOPOLOGY_FOUNDATION,
        tag="v9.9.9",
        commit="0" * 40,
        tree="0" * 40,
    )
    assert bridge._supported_legacy_topology(repository, impossible_fallback) is True

    # The split migration moves the original Git store into the pre-split
    # archive, then brain.git fetches the installed commit with --no-tags.
    # Delivery must rely on the already-proven installed identity, not expect
    # the annotated release tag to be present in the new brain store.
    _git(repository, "update-ref", "-d", f"refs/tags/{pin.tag}")
    adapter, service = _delivery_adapter(tmp_path, repository)
    service.commit = pin.commit
    _git(repository, "update-ref", "refs/dex/installed", pin.commit)
    retired_bytes = {
        relative: (repository / relative).read_bytes()
        for relative in (
            "extensions/tau-mirror/README-TAU-MIRROR.md",
            "extensions/tau-mirror/tau-mirror-integration.ts",
        )
    }

    entries = adapter.build_and_preview_delivered_release(repository, {})

    assert bridge.V161_RETIRED_MANIFEST_RELEASE == pin
    assert bridge._V161_RETIRED_MANIFEST_BLOB == "feef2bb3dd6756c7c54d76bdfd6128904c87f679"
    assert (
        bridge._V161_RETIRED_MANIFEST_SHA256
        == "edf6e98bc16063c47b362280cfa33fd10f075a5d240d5884d5ded5d894cbcc63"
    )
    assert len(entries) == 766
    assert {
        "extensions/tau-mirror/README-TAU-MIRROR.md",
        "extensions/tau-mirror/tau-mirror-integration.ts",
    }.isdisjoint(entry.path for entry in entries)
    assert {
        relative: (repository / relative).read_bytes() for relative in retired_bytes
    } == retired_bytes


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("missing", "omission set changed"),
        ("extra", "unknown unclassified path"),
        ("tampered-blob", "unknown unclassified path"),
        ("altered-mode", "unknown unclassified path"),
        ("renamed-path", "unknown unclassified path"),
    ),
)
def test_runtime_retired_manifest_adapter_refuses_real_git_identity_near_misses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    pin = _V161_RETIRED_MANIFEST_RELEASE
    repository = _historic_checkout(tmp_path, pin)
    commit, tree, manifest_blob, manifest_sha256 = _commit_retired_manifest_variant(
        repository,
        pin.commit,
        mutation,
    )
    mutated_pin = replace(
        pin,
        tag_object=commit,
        tag_object_type="commit",
        commit=commit,
        tree=tree,
    )
    _git(repository, "update-ref", f"refs/tags/{pin.tag}", commit)
    _git(repository, "update-ref", "refs/dex/installed", commit)
    monkeypatch.setattr(bridge, "V161_RETIRED_MANIFEST_RELEASE", mutated_pin, raising=False)
    monkeypatch.setattr(bridge, "_V161_RETIRED_MANIFEST_BLOB", manifest_blob, raising=False)
    monkeypatch.setattr(
        bridge,
        "_V161_RETIRED_MANIFEST_SHA256",
        manifest_sha256,
        raising=False,
    )
    adapter, service = _delivery_adapter(tmp_path, repository)
    service.commit = commit

    with pytest.raises(apply_update.ReleaseVerificationError, match=message):
        adapter.build_and_preview_delivered_release(repository, {})


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("missing", "omission set changed"),
        ("extra", "unknown unclassified path"),
        ("tampered-blob", "unknown unclassified path"),
        ("altered-mode", "unknown unclassified path"),
        ("renamed-path", "unknown unclassified path"),
    ),
)
def test_runtime_manifest_omission_adapter_refuses_real_git_identity_near_misses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    pin = bridge.MANIFESTLESS_SEMANTIC_RELEASES[1]
    repository = _historic_checkout(tmp_path, pin)
    commit, tree = _commit_manifestless_omission_variant(
        repository,
        pin.commit,
        mutation,
    )
    # Rebind only the immutable outer tree pin so this near-miss reaches the
    # production omission matcher; neither its identity function nor its
    # closed expected set is replaced here.
    mutated_pin = replace(pin, commit=commit, tree=tree)
    monkeypatch.setattr(bridge, "MANIFESTLESS_SEMANTIC_RELEASES", (mutated_pin,))
    _git(repository, "update-ref", "refs/dex/installed", commit)
    adapter, service = _delivery_adapter(tmp_path, repository)
    service.commit = commit

    with pytest.raises(apply_update.ReleaseVerificationError, match=message):
        adapter.build_and_preview_delivered_release(repository, {})


@pytest.mark.parametrize(
    ("mode", "message"),
    (("120000", "unknown symlink"), ("160000", "ambiguous")),
)
def test_runtime_manifest_omission_adapter_refuses_real_unknown_nonregular_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    message: str,
) -> None:
    defective = bridge.V175_DEFECTIVE_MANIFEST_RELEASE
    repository = _historic_checkout(tmp_path, defective)
    commit, tree = _commit_nonregular_variant(
        repository,
        defective.commit,
        mode,
        "System/unexpected-nonregular",
    )
    mutation = replace(
        defective,
        tag_object=commit,
        tag_object_type="commit",
        commit=commit,
        tree=tree,
    )
    monkeypatch.setattr(bridge, "V175_DEFECTIVE_MANIFEST_RELEASE", mutation)
    _git(repository, "update-ref", "refs/dex/installed", commit)
    adapter, service = _delivery_adapter(tmp_path, repository)
    service.commit = commit

    with pytest.raises(apply_update.ReleaseVerificationError, match=message):
        adapter.build_and_preview_delivered_release(repository, {})


def test_runtime_manifest_adapter_binds_entries_to_installed_commit_and_keeps_unknown_modern_strict(
    tmp_path: Path,
) -> None:
    pin = bridge.MANIFESTLESS_SEMANTIC_RELEASES[1]
    nearby = bridge.MANIFESTLESS_SEMANTIC_RELEASES[2]
    repository = _historic_checkout(tmp_path, pin)
    adapter, _service = _delivery_adapter(tmp_path, repository)
    _git(repository, "update-ref", "refs/dex/installed", pin.commit)

    with adapter._legacy_delivery_source():
        entries = apply_update._tree_entries(repository, repository / ".git", pin.commit)
        _git(repository, "update-ref", "refs/dex/installed", nearby.commit)
        with pytest.raises(apply_update.ReleaseVerificationError, match="identity changed"):
            apply_update._verify_manifest(repository, repository / ".git", entries)

    modern = bridge.V181_UNBOUND_JOURNEY_SOURCE.release
    _restore_checkout(repository, modern)
    _git(repository, "rm", "--quiet", "System/.installed-files.manifest")
    _git(repository, "commit", "--quiet", "-m", "test unknown manifestless modern tree")
    unknown_commit = _git(repository, "rev-parse", "HEAD^{commit}")
    _git(repository, "update-ref", "refs/dex/installed", unknown_commit)
    with adapter._legacy_delivery_source():
        entries = apply_update._tree_entries(repository, repository / ".git", unknown_commit)
        with pytest.raises(apply_update.ReleaseVerificationError, match="missing its installed-files manifest"):
            apply_update._verify_manifest(repository, repository / ".git", entries)


def test_exact_unbound_journey_source_uses_real_git_identity_and_artifact_blobs(
    tmp_path: Path,
) -> None:
    pin = bridge.V181_UNBOUND_JOURNEY_SOURCE
    repository = _historic_checkout(tmp_path, pin.release)

    assert bridge.exact_unbound_journey_source(repository, pin.release.tag) == pin.release.commit

    nearby = bridge.MANIFESTLESS_SEMANTIC_RELEASES[-1]
    release_mutations = (
        replace(pin.release, tag_object=nearby.tag_object),
        replace(pin.release, commit=nearby.commit),
        replace(pin.release, tree=nearby.tree),
    )
    for release in release_mutations:
        assert bridge.exact_unbound_journey_source(
            repository,
            pin.release.tag,
            replace(pin, release=release),
        ) is None

    first_artifact = pin.artifacts[0]
    changed_artifacts = ((first_artifact[0], "0" * 40, first_artifact[2]), *pin.artifacts[1:])
    assert bridge.exact_unbound_journey_source(
        repository,
        pin.release.tag,
        replace(pin, artifacts=changed_artifacts),
    ) is None

    _git(repository, "update-ref", f"refs/tags/{pin.release.tag}", nearby.commit)
    assert bridge.exact_unbound_journey_source(repository, pin.release.tag) is None
    assert bridge.exact_unbound_journey_source(repository, bridge.FOUNDATION.tag) is None

    _restore_checkout(repository, pin.release)
    catalog = repository / "System/.release-catalog.json"
    catalog.write_text("{}\n", encoding="utf-8")
    _git(repository, "add", "--", catalog.relative_to(repository).as_posix())
    _git(repository, "commit", "--quiet", "-m", "test catalog-bearing source")
    catalog_commit = _git(repository, "rev-parse", "HEAD^{commit}")
    catalog_tree = _git(repository, "rev-parse", "HEAD^{tree}")
    _git(repository, "update-ref", f"refs/tags/{pin.release.tag}", catalog_commit)
    catalog_pin = replace(
        pin,
        release=replace(
            pin.release,
            tag_object=catalog_commit,
            commit=catalog_commit,
            tree=catalog_tree,
        ),
    )
    assert bridge.exact_unbound_journey_source(repository, pin.release.tag, catalog_pin) is None
