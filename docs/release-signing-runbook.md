# Release signing runbook

**Who this is for:** the person who cuts Dex releases. Right now, that's Dave.

**Why it exists:** Dex already proves a release is *intact* — the files match
the hashes, nothing was tampered with in transit. Until now nothing proved *who
published it*. Anyone who got hold of the GitHub account could have pushed a
release and every Dex install would have accepted it.

Signing fixes that. You sign each release tag with a key only you hold. The
public half of that key ships inside Dex. Before installing anything, every copy
of Dex checks that the release was signed by that key — and refuses if it
wasn't.

You do this **once** to set up (Part 1, about fifteen minutes), then **one extra
flag** on each release after that (Part 2, about five seconds).

---

## Part 1 — One-time setup

### Step 1. Create the signing key in 1Password

1Password can generate the key and keep the private half where it never touches
your disk.

1. Open the 1Password app → **New Item** → **SSH Key**.
2. Choose **Generate a new key**, type **Ed25519**.
3. Name it `Dex release signing`.
4. Save it.
5. Open the item and copy the **public key**. It's one line and looks like:

   ```
   ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExample dex-release-signing
   ```

6. Turn on the 1Password SSH agent if it isn't already: 1Password →
   **Settings** → **Developer** → **Use the SSH agent**.

> **Prefer to do it in the terminal?** That works too:
>
> ```bash
> ssh-keygen -t ed25519 -C "dex-release-signing" -f ~/.ssh/dex_release_signing
> ```
>
> It will ask for a passphrase — **use one**. Then paste the *private* key
> (`~/.ssh/dex_release_signing`) into a new 1Password **SSH Key** item and
> delete the file from your Mac:
>
> ```bash
> rm ~/.ssh/dex_release_signing
> ```
>
> Keep `~/.ssh/dex_release_signing.pub` — the public half is not a secret.

The private key is now the one thing that matters. If you lose it, you can
rotate (Part 4). If someone else gets it, they can publish a release that every
Dex install trusts.

### Step 2. Tell Git to sign with it

Run these three commands once. Replace the key text with what you copied in
Step 1 — the whole line, quoted:

```bash
git config --global gpg.format ssh
git config --global user.signingkey "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExample dex-release-signing"
git config --global gpg.ssh.program "/Applications/1Password.app/Contents/MacOS/op-ssh-sign"
```

The third line is what makes 1Password do the signing. If you generated the key
with `ssh-keygen` instead and are using the normal ssh-agent, skip that third
line entirely and point at the public key file instead:

```bash
git config --global user.signingkey ~/.ssh/dex_release_signing.pub
```

Optionally, make *every* tag signed by default so you can't forget:

```bash
git config --global tag.gpgSign true
```

Check it took:

```bash
git config --global --get gpg.format
git config --global --get user.signingkey
```

### Step 3. Add your public key to the allowed-signers file

This is the file every Dex install reads to decide whose signature to trust.

Open `core/release-signing/allowed_signers` in the Dex repo. It currently
contains only comments. Add **one line** at the bottom, in this exact shape:

```
<principal> <key-type> <key-material>
```

- **principal** — any stable label. Use `releases@heydex.ai`.
- **key-type and key-material** — the first *two* words of your public key,
  i.e. `ssh-ed25519 AAAAC3Nza...`. **Leave off the trailing comment** (the
  `dex-release-signing` part). It's harmless, but the two-word form is what
  Git's format expects.

So the finished line looks like:

```
releases@heydex.ai ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExample
```

Keep the comment block above it. Never put a private key in this file — it's
public, and it ships to every user.

### Step 4. Ship it, unsigned, one last time

Cut a normal release containing that file. **This release is the bootstrap and
it does not need to be signed** (though signing it does no harm — see Part 5 for
why the first one is special either way).

From this release onward, every Dex install carries your public key. The *next*
release you publish is the first one that has to be signed.

---

## Part 2 — Cutting a signed release

The only change to your normal release process is `-s` instead of `-a` on the
tag command.

```bash
# Whatever you do today to build and commit the release, unchanged.

# Then tag it — signed:
git tag -s "dist/release/v1.65.0-$(git rev-parse --short HEAD)" -m "Dex release 1.65.0"
```

If you set `tag.gpgSign true` in Step 2, plain `git tag -a` signs too, and `-s`
is just being explicit. Being explicit is better here.

1Password will pop up and ask you to authorize the signature. That prompt is the
point of the whole exercise.

**Then verify before you push** (Part 3), and only then:

```bash
git push origin "dist/release/v1.65.0-$(git rev-parse --short HEAD)"
```

---

## Part 3 — Verify locally before pushing

Never push a release tag you haven't checked. Two commands:

```bash
# 1. Is there a signature at all, and is it from a key we trust?
git -c gpg.ssh.allowedSignersFile=core/release-signing/allowed_signers \
    verify-tag "dist/release/v1.65.0-$(git rev-parse --short HEAD)"
```

You want to see:

```
Good "git" signature for releases@heydex.ai with ED25519 key SHA256:...
```

The words **`for releases@heydex.ai`** are the ones that matter. If you see
`Good "git" signature` *without* a principal, followed by `No principal
matched`, the tag is signed but by a key that is **not** in the allowed-signers
file — users would refuse this release.

```bash
# 2. Does the tag actually carry a signature block?
git cat-file tag "dist/release/v1.65.0-$(git rev-parse --short HEAD)" | grep -c "BEGIN SSH SIGNATURE"
```

That must print `1`. If it prints `0`, the tag is unsigned — delete it, fix your
Git config, and re-tag:

```bash
git tag -d "dist/release/v1.65.0-$(git rev-parse --short HEAD)"
```

If both checks pass, push.

---

## Part 4 — What users see when a check fails

You never have to write these messages; Dex does. Knowing them helps when
someone reports one.

**The release isn't signed at all** (you forgot `-s`):

> Dex stopped this update: the release is not signed by the Dex maintainer.
> Every genuine Dex release carries a signature that Dex checks before it
> installs anything. Your copy of Dex has not been changed.

**The release is signed by a key that isn't in the allowed-signers file**
(you signed with the wrong key, or someone else published it):

> Dex stopped this update: the release's signature does not match any key Dex
> trusts. Either it was not published by the Dex maintainer, or it was altered
> after it was published. Your copy of Dex has not been changed.

**The user's machine can't check signatures at all** (their Git is older than
2.34, or `ssh-keygen` is missing):

> Dex could not check who published this release, so it did not install it.
> Checking a release signature needs Git 2.34 or newer, along with the
> ssh-keygen tool that ships with Git and OpenSSH.

In all three cases the update is **refused** and nothing on their machine
changes. Dex deliberately offers no way to skip the check — a check with an
escape hatch is not a check. If someone is stuck on the third message, updating
their Git fixes it.

If you get reports of the *second* message from users you didn't expect, treat
it as a possible compromise, not a nuisance.

---

## Part 5 — The first release is special (and why that's fine)

The allowed-signers file travels to users through the same channel it protects:
a Dex release. So the very first release carrying your key is trusted the old
way — by integrity checks alone. There's no way around that, and pretending
otherwise would be dishonest.

From the *second* release onward the protection is real. When Dex checks release
N, it reads the allowed-signers file already sitting on the user's disk, put
there by release N−1, which that user already accepted. It never trusts the copy
inside the release being examined — an attacker able to forge the release could
forge that copy too.

Practical consequence: **the bootstrap release is the one moment worth being
careful about.** Publish it from a machine you trust, and check afterwards that
the key in the published `core/release-signing/allowed_signers` is really yours.

---

## Part 6 — Rotating the key

Rotation is not a special mechanism. It's a normal release that happens to
change one file.

Rotate when: you think the key may have leaked, you're changing machines or
password managers, or on a schedule you set for yourself.

1. Create the new key (Part 1, Step 1). Give it a distinct 1Password name, e.g.
   `Dex release signing 2027`.
2. Add the new key's line to `core/release-signing/allowed_signers`,
   **keeping the old line**. Two lines now:

   ```
   releases@heydex.ai ssh-ed25519 AAAA...OLD...
   releases@heydex.ai ssh-ed25519 AAAA...NEW...
   ```

3. Cut that release **signed with the OLD key**. This is the important part:
   the release that introduces the new key is authenticated by the key it
   replaces, so users can verify the handover with what they already trust.
4. Switch your Git config to the new key (Part 1, Step 2).
5. Cut the next release signed with the **new** key. Verify it (Part 3).
6. After at least one more release, remove the old line and cut a release
   **signed with the new key**. Now the old key is powerless.

Do not skip step 3 by shipping a new key inside a release signed by the new key
— users have no reason to trust that, and Dex will refuse it.

**If the key is lost rather than leaked** and you can't sign step 3, you're back
in the bootstrap situation: publish a release that adds the new key, tell users
plainly in the release notes and on heydex.ai that a key rotation happened and
why, and expect that release to be trusted the old way. Say so out loud rather
than quietly.

**If the key is stolen**, rotate immediately, publish an advisory naming the
affected version range, and don't wait for step 6 — drop the old line in the
same release if you can still sign with the old key, and accept a bootstrap gap
if you can't.

---

## Where the pieces live

| Thing | Path |
|---|---|
| The trusted-key list that ships to users | `core/release-signing/allowed_signers` |
| Notes on that file | `core/release-signing/README.md` |
| The check during release awareness and delivery | `core/utils/update_verifier.py` |
| The last check before a release is applied | `core/update/apply_update.py` |
| Tests, including real signed-tag fixtures | `core/tests/test_update_checker.py`, `core/tests/test_apply_update.py` |

## Quick reference

```bash
# One-time
git config --global gpg.format ssh
git config --global user.signingkey "ssh-ed25519 AAAA..."
git config --global gpg.ssh.program "/Applications/1Password.app/Contents/MacOS/op-ssh-sign"
git config --global tag.gpgSign true

# Each release
TAG="dist/release/v1.65.0-$(git rev-parse --short HEAD)"
git tag -s "$TAG" -m "Dex release 1.65.0"
git -c gpg.ssh.allowedSignersFile=core/release-signing/allowed_signers verify-tag "$TAG"
git push origin "$TAG"
```
