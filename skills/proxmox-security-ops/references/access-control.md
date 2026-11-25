# Access control reference

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: pve-user-management
    source_url: https://pve.proxmox.com/pve-docs/chapter-pveum.html
    verified_on: 2026-09-27
    review_by: 2027-03-27
    claim: "Realms pam, pve, ldap, ad, openid in /etc/pve/domains.cfg; tokens privsep default, expire, secret shown once; TFA TOTP/WebAuthn/recovery/Yubico, realm-enforced TFA, pveum user tfa unlock."
-->

Labels: **[V]** checked against pve.proxmox.com docs on 2026-09-27; **[I]** inferred, so re-verify.

## Users, groups, roles, ACLs

```bash
pveum group add admins                                         # [I] syntax
pveum user add alice@pve --comment "Alice" ; pveum passwd alice@pve   # [V]/[I]
pveum user modify alice@pve --group admins                     # [V]
pveum acl modify / --group admins --role Administrator         # [V]
pveum acl modify /vms --user joe@pve --role PVEAuditor         # [V]
pveum role add VM_Power-only --privs "VM.PowerMgmt VM.Console" # [V]
pveum user permissions joe@pve                                  # [V] effective rights
```

Design rules [I]:
- Grant roles to **groups**, not individual users; users join groups.
- Put tenant or team guests in a **pool** and grant on `/pool/<name>`.
- `PVEAuditor` on `/` for monitoring; never `Administrator` for a dashboard.
- `Permissions.Modify` lets its holder grant themselves more; `Sys.Modify` changes host settings. Treat both as admin-grade.
- Users can only hand out roles whose privileges they hold (e.g. `PVEVMAdmin` can assign `PVEVMUser`, not `PVEAdmin`) [V].

## Realms

| Realm | Notes |
|---|---|
| `pam` | Linux accounts on the node; users must exist on **every** node; `root@pam` always works and cannot be deleted [V] |
| `pve` | Proxmox's own password store, cluster-wide; best for local non-root accounts [V] |
| LDAP / AD | Bind password in `/etc/pve/priv/realm/<realm>.pw` [V]; `pveum realm sync <realm>` imports users/groups (groups get a `-<realm>` suffix) [V]; use LDAPS/StartTLS [I]; AD case sensitivity via `--case-sensitive 0` [V] |
| OpenID Connect | `pveum realm add <id> --type openid --issuer-url <url> --client-id <id> --username-claim <claim>` [V]; `groups-claim` maps groups [V]; good for SSO with Keycloak/Authentik/Entra [I] |

## API tokens

- Privilege separation on by default: token rights = user rights ∩ token ACLs [V]. Turn it off only when the integration truly needs the user's full rights [V].
- `--expire <epoch>`; revoke a token without disabling the user [V].
- One token per integration (backup tool, Terraform, monitoring, HA dashboard); name it after the consumer [I].
- Store secrets in the consumer's secret store, never in a repo [I].

## TFA

- Types: TOTP, WebAuthn (needs the WebAuthn origin configured on the server), Yubico OTP (realm), single-use **recovery keys** [V].
- Realm-enforced TFA: only users with TFA configured can log in [V].
- Lockout after too many failed second factors; recovery key login unlocks; admin: `pveum user tfa unlock <user>` [V].
- Give `root@pam` TFA plus printed recovery keys stored offline [I]. Console (IPMI/iKVM) access remains the true break-glass: at the console, `passwd root` resets the PAM password, and `pveum user tfa delete root@pam` removes a lost second factor [I: check `pveum user tfa --help`].

## PVE 9 privilege changes

- PVE 9 privileges include `VM.GuestAgent.Audit`, `.FileRead`, `.FileWrite`, `.FileSystemMgmt`, `.Unrestricted` and `VM.Replicate` [V]. `VM.Monitor` is no longer in the privilege list [V: absent from the PVE 9 docs]; custom roles and tokens built on it need review after the 8 to 9 upgrade [I].

Firewall configuration lives in [firewall.md](firewall.md).
