---
name: windows-sso
description: Use when configuring Single Sign-On (SSO) on Windows — Active Directory Federation Services (AD FS), Azure AD / Entra ID SSO, SAML 2.0, OAuth 2.0/OIDC, Kerberos delegation, Windows Integrated Authentication (WIA/SPNEGO), claims-based authentication, Web Application Proxy (WAP), conditional access policies, MFA integration, certificate-based auth, SSO troubleshooting, and hybrid identity (AD Connect). Part of the windows-* skill family.
family: windows
disambiguation: Configuring SSO INFRASTRUCTURE on Windows — AD FS, Entra ID, SAML and OIDC federation. Core directory administration is windows-ad-admin; authenticating a Python client is ms-office-enterprise-sso-python.
---

# Windows Single Sign-On (SSO) Administration

Companion skill to `windows-powershell` (parent), `windows-ps-server-admin`, and `windows-ps-security`. Covers enterprise SSO infrastructure across on-premises AD FS, hybrid Azure AD / Entra ID, and federation protocols. Targets Windows Server 2019/2022/2025 and Microsoft Entra ID (formerly Azure AD).

<HARD-RULE>
NEVER EXPOSE AD FS DIRECTLY TO THE INTERNET. Always deploy Web Application Proxy (WAP) in a perimeter/DMZ network as the reverse proxy for AD FS. Direct internet exposure of AD FS servers creates a critical attack surface for credential harvesting, token forgery (Golden SAML), and denial-of-service. The WAP server handles external authentication requests and forwards them to the internal AD FS farm.
```powershell
# Verify AD FS is not listening on external interfaces — should only bind to internal IPs
Get-AdfsProperties | Select-Object HostName, HttpsPort, Identifier
# WAP must be the only externally facing component
Get-WebApplicationProxyApplication | Select-Object Name, ExternalUrl, BackendServerUrl
```
</HARD-RULE>

<HARD-RULE>
ALWAYS BACK UP AD FS TOKEN SIGNING AND DECRYPTION CERTIFICATES. Loss of these certificates means all federation trusts break and all issued tokens become invalid. Export certificates immediately after installation and after every rotation. Store backups in a secure, offline location with restricted access.
```powershell
# Export token signing certificate (include private key)
$cert = Get-AdfsCertificate -CertificateType Token-Signing | Where-Object { $_.IsPrimary }
$password = Read-Host -AsSecureString -Prompt "Export password"
Export-PfxCertificate -Cert "Cert:\LocalMachine\My\$($cert.Thumbprint)" `
    -FilePath "C:\ADFSBackup\TokenSigning_$(Get-Date -Format yyyyMMdd).pfx" `
    -Password $password
# Export token decryption certificate
$decryptCert = Get-AdfsCertificate -CertificateType Token-Decryption | Where-Object { $_.IsPrimary }
Export-PfxCertificate -Cert "Cert:\LocalMachine\My\$($decryptCert.Thumbprint)" `
    -FilePath "C:\ADFSBackup\TokenDecryption_$(Get-Date -Format yyyyMMdd).pfx" `
    -Password $password
```
</HARD-RULE>

<HARD-RULE>
ROTATE AD FS CERTIFICATES BEFORE EXPIRY. Expired token signing or SSL certificates cause immediate SSO outages for all relying parties. Monitor certificate expiration dates and rotate at least 30 days before expiry. Use AutoCertificateRollover where possible, but always verify the rollover occurred.
```powershell
# Check all AD FS certificate expiration dates
Get-AdfsCertificate | Select-Object CertificateType, Thumbprint, IsPrimary,
    @{N='NotAfter';E={$_.Certificate.NotAfter}},
    @{N='DaysUntilExpiry';E={($_.Certificate.NotAfter - (Get-Date)).Days}} |
    Format-Table -AutoSize

# Verify auto-rollover is enabled
Get-AdfsProperties | Select-Object AutoCertificateRollover

# Force certificate rollover if nearing expiry
Update-AdfsCertificate -CertificateType Token-Signing -Urgent
```
</HARD-RULE>

<HARD-RULE>
PROTECT THE AZURE AD CONNECT SERVER AS TIER 0 INFRASTRUCTURE. The AD Connect server has full read/write access to both on-premises AD and Entra ID. Compromise of this server means compromise of the entire hybrid identity environment. Apply the same security controls as domain controllers: restricted admin access, no internet browsing, dedicated admin workstations, PAM/PIM for access, full audit logging, and network isolation.
```powershell
# Verify AD Connect server is domain-joined and in a protected OU
Get-ADComputer -Identity "YOURAADC-SERVER" -Properties MemberOf, DistinguishedName |
    Select-Object Name, DistinguishedName, @{N='OUPath';E={($_.DistinguishedName -split ',',2)[1]}}
# Check who has local admin on the AD Connect server
Invoke-Command -ComputerName YOURAADC-SERVER -ScriptBlock {
    Get-LocalGroupMember -Group "Administrators" | Select-Object Name, ObjectClass, PrincipalSource
}
```
</HARD-RULE>

---

## Reference Files

Detailed code examples, patterns, and configuration are in the reference files below. Read the relevant file when working on that area.

| File | Covers |
|---|---|
| [adfs-azuread-saml.md](adfs-azuread-saml.md) | AD FS configuration, Azure AD/Entra ID SSO, SAML 2.0 implementation |
| [oauth-kerberos-wia.md](oauth-kerberos-wia.md) | OAuth 2.0/OpenID Connect, Kerberos delegation, Windows Integrated Authentication |
| [wap-mfa-hybrid-troubleshooting.md](wap-mfa-hybrid-troubleshooting.md) | Web Application Proxy, Conditional Access/MFA, certificate-based authentication, Azure AD Connect hybrid identity, and SSO troubleshooting |

---

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Configuring SSO without testing token expiration and refresh | Users get logged out mid-session; refresh tokens fail silently; support tickets spike | Test full token lifecycle: login, refresh, expiration, re-authentication; set refresh token lifetime appropriately |
| Using NTLM fallback as primary authentication | NTLM is vulnerable to relay attacks and pass-the-hash; SSO benefits are lost when Kerberos fails silently to NTLM | Enforce Kerberos; audit NTLM usage; fix SPN registration and DNS issues rather than allowing NTLM fallback |
| Not registering SPNs correctly for service accounts | Kerberos delegation fails; SSO silently falls back to NTLM or prompts for credentials; intermittent auth failures | Use `setspn -L` to verify; register SPNs on the correct service account; check for duplicates with `setspn -X` |
| Implementing SSO without session timeout policies | Users remain authenticated indefinitely; shared workstations expose sessions to unauthorized users | Configure session timeouts (idle and absolute) matching security policy; force re-auth for sensitive operations |
| Using self-signed certificates for SAML/OIDC in production | Certificate expiration causes complete SSO outage; browsers warn users; trust chain is broken | Use CA-signed certificates; set calendar reminders for renewal 30 days before expiry; automate with ACME where possible |

---

## Related Skills

| Skill | Scope |
|---|---|
| `windows-powershell` | Core PowerShell language, modules, remoting, scripting patterns |
| `windows-ps-server-admin` | AD DS, DNS, DHCP, IIS, Hyper-V, WSUS, AD CS, server roles |
| `windows-ps-security` | Windows Firewall, Defender, BitLocker, audit policy, AppLocker |
| `windows-cmd` | Legacy CMD commands, batch scripting, system utilities |
| `linux-centrify` | Centrify/Delinea on Linux — AD-joined Linux machines in the same SSO infrastructure |
