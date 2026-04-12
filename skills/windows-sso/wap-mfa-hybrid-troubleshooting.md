# WAP, Conditional Access, Certificates, Hybrid, and Troubleshooting

Reference file for the `windows-sso` skill. Covers Web Application Proxy, Conditional Access/MFA, certificate-based authentication, Azure AD Connect hybrid identity, and SSO troubleshooting.

## 7. Web Application Proxy (WAP)

### Install WAP Role

```powershell
# Install Remote Access role with WAP feature
Install-WindowsFeature -Name Web-Application-Proxy -IncludeManagementTools

# Verify installation
Get-WindowsFeature -Name Web-Application-Proxy | Select-Object Name, Installed
```

### Configure WAP with AD FS

```powershell
# Import the AD FS SSL certificate on the WAP server
$certPw = Read-Host -AsSecureString "PFX password"
Import-PfxCertificate -FilePath "C:\Certs\adfs-ssl.pfx" `
    -CertStoreLocation Cert:\LocalMachine\My -Password $certPw

$wapCertThumbprint = (Get-ChildItem Cert:\LocalMachine\My |
    Where-Object { $_.Subject -like "*fs.contoso.com*" }).Thumbprint

# Install and configure WAP — connect to AD FS farm
# Use an AD FS admin credential
$adfsCred = Get-Credential -Message "AD FS service account or admin"
Install-WebApplicationProxy `
    -CertificateThumbprint $wapCertThumbprint `
    -FederationServiceName "fs.contoso.com" `
    -FederationServiceTrustCredential $adfsCred

# Verify WAP configuration
Get-WebApplicationProxyConfiguration | Select-Object ADFSUrl, ADFSTokenSigningCertificatePublicKey
```

### Publish AD FS Through WAP

```powershell
# AD FS is automatically published when WAP is configured
# Verify it is accessible
Get-WebApplicationProxyApplication | Where-Object { $_.Name -like "*adfs*" } |
    Select-Object Name, ExternalUrl, BackendServerUrl, ExternalPreauthentication
```

### Publish Web Applications

```powershell
# Publish with AD FS pre-authentication (SSO-enabled, most secure)
Add-WebApplicationProxyApplication `
    -Name "Contoso HR Portal" `
    -ExternalUrl "https://hr.contoso.com/" `
    -BackendServerUrl "https://hr-internal.contoso.com/" `
    -ExternalCertificateThumbprint $wapCertThumbprint `
    -ExternalPreauthentication ADFS `
    -ADFSRelyingPartyName "Contoso HR Portal"

# Publish with pass-through authentication (no pre-auth, app handles auth)
Add-WebApplicationProxyApplication `
    -Name "Contoso API Gateway" `
    -ExternalUrl "https://api.contoso.com/" `
    -BackendServerUrl "https://api-internal.contoso.com/" `
    -ExternalCertificateThumbprint $wapCertThumbprint `
    -ExternalPreauthentication PassThrough

# List all published applications
Get-WebApplicationProxyApplication | Format-Table Name, ExternalUrl,
    BackendServerUrl, ExternalPreauthentication, Status -AutoSize

# Update a published application
Set-WebApplicationProxyApplication -Id (Get-WebApplicationProxyApplication -Name "Contoso HR Portal").Id `
    -BackendServerUrl "https://hr-new-internal.contoso.com/"

# Remove a published application
Remove-WebApplicationProxyApplication -Name "Old App"

# Check WAP health
Get-WebApplicationProxyHealth | Format-Table HealthState, ComponentName, RemoteAccessServer -AutoSize
```

### WAP + AD FS Topology

```
Recommended Architecture:
                 Internet
                    │
              ┌─────┴─────┐
              │  Firewall  │
              └─────┬─────┘
                    │
         ┌──────────┴──────────┐
         │    DMZ / Perimeter   │
         │  ┌───────────────┐  │
         │  │  WAP Server 1 │  │     ← Handles external HTTPS (443)
         │  │  WAP Server 2 │  │     ← Load-balanced for HA
         │  └───────┬───────┘  │
         └──────────┼──────────┘
              ┌─────┴─────┐
              │  Firewall  │          ← Only allow 443 from WAP to AD FS
              └─────┬─────┘
         ┌──────────┴──────────┐
         │   Internal Network   │
         │  ┌───────────────┐  │
         │  │ AD FS Server 1│  │     ← Internal federation service
         │  │ AD FS Server 2│  │     ← Farm for high availability
         │  └───────────────┘  │
         │  ┌───────────────┐  │
         │  │ Domain Contrlr│  │     ← AD authentication back-end
         │  └───────────────┘  │
         └─────────────────────┘

Certificate Requirements:
- WAP servers: SSL cert matching federation service name (e.g., fs.contoso.com)
- WAP servers: SSL certs for each published application external URL
- AD FS servers: Same SSL cert as WAP for the federation service name
- AD FS servers: Token signing and token decryption certificates (self-signed or CA-issued)
```

---

## 8. Conditional Access & MFA

### Entra ID Conditional Access Policies

```powershell
Connect-MgGraph -Scopes "Policy.ReadWrite.ConditionalAccess", "Policy.Read.All"

# List all conditional access policies
Get-MgIdentityConditionalAccessPolicy | Select-Object DisplayName, State,
    @{N='Conditions';E={$_.Conditions | ConvertTo-Json -Depth 3}} | Format-List

# Create a conditional access policy: Require MFA for all users accessing cloud apps
$caPolicy = @{
    DisplayName = "Require MFA for All Cloud Apps"
    State       = "enabledForReportingButNotEnforced"  # Use "enabled" for production
    Conditions  = @{
        Users = @{
            IncludeUsers = @("All")
            ExcludeUsers = @("BREAK-GLASS-ACCOUNT-ID")  # Always exclude break-glass
        }
        Applications = @{
            IncludeApplications = @("All")
        }
        ClientAppTypes = @("browser", "mobileAppsAndDesktopClients")
    }
    GrantControls = @{
        Operator        = "OR"
        BuiltInControls = @("mfa")
    }
}
New-MgIdentityConditionalAccessPolicy -BodyParameter $caPolicy

# Create policy: Block legacy authentication
$blockLegacy = @{
    DisplayName = "Block Legacy Authentication"
    State       = "enabled"
    Conditions  = @{
        Users = @{ IncludeUsers = @("All") }
        Applications = @{ IncludeApplications = @("All") }
        ClientAppTypes = @("exchangeActiveSync", "other")
    }
    GrantControls = @{
        Operator        = "OR"
        BuiltInControls = @("block")
    }
}
New-MgIdentityConditionalAccessPolicy -BodyParameter $blockLegacy

# Create policy: Require compliant device for specific app
$compliantDevice = @{
    DisplayName = "Require Compliant Device for HR App"
    State       = "enabled"
    Conditions  = @{
        Users        = @{ IncludeGroups = @("HR-USERS-GROUP-ID") }
        Applications = @{ IncludeApplications = @("HR-APP-ID") }
        Platforms    = @{
            IncludePlatforms = @("all")
        }
    }
    GrantControls = @{
        Operator        = "OR"
        BuiltInControls = @("compliantDevice")
    }
}
New-MgIdentityConditionalAccessPolicy -BodyParameter $compliantDevice

# Create policy: Require MFA from untrusted locations
$locationPolicy = @{
    DisplayName = "MFA from Untrusted Locations"
    State       = "enabled"
    Conditions  = @{
        Users        = @{ IncludeUsers = @("All") }
        Applications = @{ IncludeApplications = @("All") }
        Locations    = @{
            IncludeLocations = @("All")
            ExcludeLocations = @("AllTrusted")  # Named location "AllTrusted"
        }
    }
    GrantControls = @{
        Operator        = "OR"
        BuiltInControls = @("mfa")
    }
}
New-MgIdentityConditionalAccessPolicy -BodyParameter $locationPolicy

# Define a named (trusted) location
$namedLocation = @{
    "@odata.type" = "#microsoft.graph.ipNamedLocation"
    DisplayName   = "Corporate Network"
    IsTrusted     = $true
    IpRanges      = @(
        @{ "@odata.type" = "#microsoft.graph.iPv4CidrRange"; CidrAddress = "203.0.113.0/24" },
        @{ "@odata.type" = "#microsoft.graph.iPv4CidrRange"; CidrAddress = "198.51.100.0/24" }
    )
}
New-MgIdentityConditionalAccessNamedLocation -BodyParameter $namedLocation
```

### AD FS Access Control Policies

```powershell
# List built-in access control policies
Get-AdfsAccessControlPolicy | Select-Object Name, Identifier, IsBuiltIn | Format-Table -AutoSize

# Apply an access control policy to a relying party trust
Set-AdfsRelyingPartyTrust -TargetName "Custom App" `
    -AccessControlPolicyName "Permit everyone and require MFA from extranet"

# Create custom AD FS access control policy (require MFA for external access)
$customPolicy = New-AdfsAccessControlPolicy `
    -Name "Require MFA Outside Corporate" `
    -Identifier "CustomMFAPolicy" `
    -Description "Permits all but requires MFA from non-corporate networks"

# AD FS additional authentication (MFA) configuration
# Register MFA providers
Get-AdfsAuthenticationProvider | Select-Object Name, AdminName, IsExternalProvider

# Set MFA as additional authentication for extranet
Set-AdfsGlobalAuthenticationPolicy `
    -AdditionalAuthenticationProvider @("AzureMfaAuthentication") `
    -AllowAdditionalAuthenticationAsPrimary $false

# Configure per-relying-party MFA
$mfaRules = @'
@RuleTemplate = "Authorization"
@RuleName = "Require MFA for extranet"
c:[Type == "http://schemas.microsoft.com/ws/2012/01/insidecorporatenetwork", Value == "false"]
=> issue(Type = "http://schemas.microsoft.com/ws/2008/06/identity/claims/authenticationmethod",
         Value = "http://schemas.microsoft.com/claims/multipleauthn");
'@
Set-AdfsRelyingPartyTrust -TargetName "Sensitive App" -AdditionalAuthenticationRules $mfaRules
```

### MFA Methods and Registration

```powershell
# List MFA methods registered for a user (Entra ID)
$userId = (Get-MgUser -Filter "userPrincipalName eq 'user@contoso.com'").Id
Get-MgUserAuthenticationMethod -UserId $userId |
    Select-Object Id, @{N='Type';E={$_.'@odata.type'}} | Format-Table

# List phone methods
Get-MgUserAuthenticationPhoneMethod -UserId $userId

# List FIDO2 security keys
Get-MgUserAuthenticationFido2Method -UserId $userId

# List Microsoft Authenticator registrations
Get-MgUserAuthenticationMicrosoftAuthenticatorMethod -UserId $userId

# Reset a user's MFA (force re-registration)
# Remove specific method
Remove-MgUserAuthenticationPhoneMethod -UserId $userId -PhoneAuthenticationMethodId "METHOD_ID"
```

---

## 9. Certificate-Based Authentication

### Smart Card Logon Configuration

```powershell
# Verify smart card certificate templates are available
# Requires AD CS (Certificate Services) — see windows-ps-server-admin
Get-CATemplate | Where-Object { $_.Name -like "*SmartCard*" }

# Enroll a smart card certificate for a user
# Using certreq (command-line enrollment)
# Create an INF file for the request
$inf = @"
[NewRequest]
Subject = "CN=John Smith, OU=Users, DC=contoso, DC=com"
KeySpec = 1
KeyLength = 2048
Exportable = FALSE
MachineKeySet = FALSE
ProviderName = "Microsoft Base Smart Card Crypto Provider"
ProviderType = 1
RequestType = CMC
[RequestAttributes]
CertificateTemplate = SmartcardLogon
"@
$inf | Out-File "C:\Temp\smartcard-request.inf"
certreq -new "C:\Temp\smartcard-request.inf" "C:\Temp\smartcard-request.req"
certreq -submit "C:\Temp\smartcard-request.req" "C:\Temp\smartcard-cert.cer"

# Check smart card reader status
certutil -scinfo

# Map a certificate to an AD user (explicit mapping)
$cert = Get-PfxCertificate -FilePath "C:\Temp\user-cert.cer"
Set-ADUser -Identity jsmith -Certificates @{Add=$cert}

# Verify certificate mapping
Get-ADUser -Identity jsmith -Properties Certificates | Select-Object -ExpandProperty Certificates
```

### AD CS Integration for SSO Certificates

```powershell
# Install and configure AD CS for SSO certificate issuance
Install-WindowsFeature -Name ADCS-Cert-Authority -IncludeManagementTools

# Configure the CA (Enterprise Root or Subordinate)
Install-AdcsCertificationAuthority `
    -CAType EnterpriseRootCA `
    -CryptoProviderName "RSA#Microsoft Software Key Storage Provider" `
    -KeyLength 4096 `
    -HashAlgorithmName SHA256 `
    -ValidityPeriod Years -ValidityPeriodUnits 10

# Create a certificate template for SSO (duplicate the Web Server template)
# This requires ADSI editing or the certtmpl.msc MMC snap-in
# PowerShell approach: export, modify, and import template
$ldapPath = "LDAP://CN=Certificate Templates,CN=Public Key Services,CN=Services,CN=Configuration,DC=contoso,DC=com"
# Use certutil to list templates
certutil -CATemplates
certutil -Template

# Issue certificates automatically via GPO autoenrollment
# GPO: Computer Configuration → Policies → Windows Settings → Security Settings →
#       Public Key Policies → Certificate Services Client - Auto-Enrollment
# Enable: "Enroll certificates automatically"
```

### Entra ID Certificate-Based Authentication (CBA)

```powershell
# Upload trusted CA certificate to Entra ID
Connect-MgGraph -Scopes "Organization.ReadWrite.All"

$caCert = [System.IO.File]::ReadAllBytes("C:\Certs\contoso-root-ca.cer")
$caCertBase64 = [Convert]::ToBase64String($caCert)

$certConfig = @{
    CertificateAuthorities = @(
        @{
            Certificate           = $caCertBase64
            CertificateRevocationListUrl = "http://crl.contoso.com/crld/contoso-ca.crl"
            IsRootAuthority       = $true
            DeltaCertificateRevocationListUrl = ""
        }
    )
}
# Use the API to update certificate-based auth configuration
$orgId = (Get-MgOrganization).Id
Update-MgOrganizationCertificateBasedAuthConfiguration -OrganizationId $orgId -BodyParameter $certConfig

# Configure Entra ID CBA authentication method policy
$cbaPolicy = @{
    State = "enabled"
    IncludeTargets = @(
        @{
            TargetType = "group"
            Id         = "ALL-USERS-GROUP-ID"
        }
    )
}
# Enable CBA in authentication methods
# Azure Portal: Security → Authentication methods → Certificate-Based Authentication → Enable
```

### AD FS Certificate Authentication

```powershell
# Enable certificate authentication on AD FS
Set-AdfsGlobalAuthenticationPolicy -PrimaryExtranetAuthenticationProvider @(
    "FormsAuthentication",
    "CertificateAuthentication"
)
Set-AdfsGlobalAuthenticationPolicy -PrimaryIntranetAuthenticationProvider @(
    "WindowsAuthentication",
    "CertificateAuthentication"
)

# Configure AD FS to accept client certificates on a dedicated port
Set-AdfsAlternateTlsClientBinding -Thumbprint $sslThumbprint -Port 49443
# Users accessing https://fs.contoso.com:49443/adfs/ls/ will be prompted for certificate

# Configure certificate authentication endpoint
Enable-AdfsEndpoint -TargetAddressPath "/adfs/services/trust/13/certificatemixed"

# Restart AD FS
Restart-Service adfssrv
```

---

## 10. Hybrid Identity (Azure AD Connect)

### Installation and Configuration

```powershell
# Download Azure AD Connect from Microsoft
# https://www.microsoft.com/en-us/download/details.aspx?id=47594
# Run AzureADConnect.msi on a domain-joined server

# Pre-requisites check
# .NET Framework 4.7.2+, TLS 1.2 enabled, SQL Server (Express included)
# Verify .NET version
Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full" -Name Release

# Ensure TLS 1.2 is enabled
$tls12 = @(
    "HKLM:\SOFTWARE\Microsoft\.NETFramework\v4.0.30319",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\.NETFramework\v4.0.30319"
)
foreach ($path in $tls12) {
    Set-ItemProperty -Path $path -Name "SchUseStrongCrypto" -Value 1 -Type DWord
    Set-ItemProperty -Path $path -Name "SystemDefaultTlsVersions" -Value 1 -Type DWord
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
```

### Sync Methods Comparison

```
┌─────────────────────────┬──────────────────┬──────────────────┬──────────────────┐
│ Feature                 │ Password Hash    │ Pass-Through     │ Federation       │
│                         │ Sync (PHS)       │ Auth (PTA)       │ (AD FS)          │
├─────────────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Password stored in      │ Cloud (hash of   │ On-premises only │ On-premises only │
│                         │ hash)            │                  │                  │
│ On-prem infra needed    │ AD Connect only  │ AD Connect +     │ AD Connect +     │
│                         │                  │ PTA Agents       │ AD FS Farm + WAP │
│ Smart lockout           │ Cloud-enforced   │ On-prem policy   │ On-prem policy   │
│ MFA options             │ Full Entra MFA   │ Full Entra MFA   │ AD FS MFA +      │
│                         │                  │                  │ Entra MFA        │
│ Conditional Access      │ Full support     │ Full support     │ AD FS policies + │
│                         │                  │                  │ Entra CA         │
│ Complexity              │ Low              │ Medium           │ High             │
│ HA requirement          │ Staging server   │ Multiple agents  │ Farm + WAP       │
│ Password change         │ Cloud + writeback│ Real-time        │ Real-time        │
│ Leaked cred detection   │ Yes              │ No               │ No               │
└─────────────────────────┴──────────────────┴──────────────────┴──────────────────┘

Microsoft Recommendation: PHS as primary or backup for all deployments.
```

### AD Connect Management

```powershell
# Import the AD Sync module (on the AD Connect server)
Import-Module ADSync

# Check sync status
Get-ADSyncScheduler | Select-Object AllowedSyncCycleInterval, CurrentlyEffectiveSyncCycleInterval,
    NextSyncCyclePolicyType, NextSyncCycleStartTimeInUTC, SyncCycleEnabled

# Trigger a delta sync manually
Start-ADSyncSyncCycle -PolicyType Delta

# Trigger a full sync (use sparingly — resource intensive)
Start-ADSyncSyncCycle -PolicyType Initial

# Check last sync result
Get-ADSyncRunProfileResult -ConnectorName "contoso.com" | Select-Object -First 5 |
    Format-Table StartDate, EndDate, Result -AutoSize

# Check connector status
Get-ADSyncConnector | Select-Object Name, Type, ConnectorTypeName | Format-Table -AutoSize

# View sync errors
Get-ADSyncRunStepResult | Where-Object { $_.StepResult -ne "success" } | Select-Object -First 10

# Check AD Connect version
Get-ADSyncGlobalSettings | Select-Object -ExpandProperty Parameters |
    Where-Object { $_.Name -eq "Microsoft.Synchronize.ServerConfigurationVersion" }
```

### Sync Rules and Filtering

```powershell
# List all sync rules
Get-ADSyncRule | Select-Object Name, Direction, Connector, Precedence, Disabled |
    Sort-Object Precedence | Format-Table -AutoSize

# View a specific sync rule
Get-ADSyncRule -Identifier "RULE-GUID" | Format-List *

# OU-based filtering (sync only specific OUs)
# Configure via AD Connect wizard, or check current configuration:
$connector = Get-ADSyncConnector | Where-Object { $_.ConnectorTypeName -eq "AD" }
$connector.Partitions | ForEach-Object {
    $_.ConnectorPartitionScope.ContainerInclusionList
    $_.ConnectorPartitionScope.ContainerExclusionList
}

# Group-based filtering (sync only members of a specific group)
# Set via AD Connect wizard: "Synchronize selected domains and OUs"
# Then create a sync rule or use pilot group

# Attribute-based filtering — create custom inbound sync rule
# Example: Only sync users with department = "IT"
$filterRule = @{
    Name             = "In from AD - Filter Department"
    Direction        = "Inbound"
    Precedence       = 50
    SourceObjectType = "user"
    TargetObjectType = "person"
    Connector        = $connector.Identifier
    ScopeFilter      = @(
        @{
            Clauses = @(
                @{ Attribute = "department"; Operator = "NOTEQUAL"; Value = "IT" }
            )
        }
    )
    LinkType         = "Join"
}
# Note: Custom sync rules are best created through the Synchronization Rules Editor GUI
```

### Staging Mode

```powershell
# Enable staging mode (AD Connect server syncs but does NOT export changes)
# Useful for: disaster recovery standby, testing new sync rules, migration
# Configure via AD Connect wizard or:
Set-ADSyncScheduler -StagingModeEnabled $true

# Verify staging mode
Get-ADSyncScheduler | Select-Object StagingModeEnabled

# When promoting staging server to active:
Set-ADSyncScheduler -StagingModeEnabled $false
# IMPORTANT: Disable the old active server first to prevent conflicts
```

---

## 11. SSO Troubleshooting

### AD FS Event Logs

```powershell
# AD FS event logs live under Applications and Services Logs → AD FS
# Key event log sources and IDs:

# Event ID 364 — Encountered error during federation passive request (common SSO failure)
Get-WinEvent -LogName "AD FS/Admin" -FilterXPath "*[System[EventID=364]]" -MaxEvents 10 |
    Select-Object TimeCreated, @{N='Message';E={$_.Message.Substring(0, [Math]::Min(500, $_.Message.Length))}} |
    Format-List

# Event ID 501 — Token validation failed
Get-WinEvent -LogName "AD FS/Admin" -FilterXPath "*[System[EventID=501]]" -MaxEvents 10 |
    Select-Object TimeCreated, Message | Format-List

# Event ID 1021 — Access denied to relying party (authorization failure)
Get-WinEvent -LogName "AD FS/Admin" -FilterXPath "*[System[EventID=1021]]" -MaxEvents 10 |
    Select-Object TimeCreated, Message | Format-List

# Comprehensive AD FS error log query (last 24 hours)
$startTime = (Get-Date).AddHours(-24)
Get-WinEvent -LogName "AD FS/Admin" -FilterXPath "*[System[Level<=3]]" -MaxEvents 100 |
    Where-Object { $_.TimeCreated -ge $startTime } |
    Select-Object TimeCreated, Id, LevelDisplayName, Message |
    Format-Table -Wrap

# Enable AD FS debug/verbose logging
Set-AdfsProperties -LogLevel @("Errors", "Warnings", "Information", "FailureAudits", "SuccessAudits", "Verbose")

# AD FS event ID reference:
# 111  — AD FS service started
# 264  — Certificate configuration warning
# 299  — Audit success (token issued)
# 325  — Token signing certificate renewal attempt
# 364  — Passive federation request error
# 501  — Token validation failure
# 510  — Token issuance failure (additional info)
# 1007 — Certificate error (expired or not found)
# 1021 — Access denied / authorization failure
# 1035 — Extranet lockout triggered
```

### AD FS Server Health Check

```powershell
# Comprehensive AD FS health test
Test-AdfsServerHealth | Format-Table Name, Result, Detail -AutoSize -Wrap

# Check specific aspects
Test-AdfsServerHealth | Where-Object { $_.Result -ne "Pass" } |
    Format-List Name, Result, Detail, Output

# Check AD FS service status
Get-Service adfssrv, W3SVC | Select-Object Name, Status, StartType

# Verify AD FS SSL certificate binding
netsh http show sslcert hostnameport=fs.contoso.com:443

# Test AD FS endpoints
$metadataUrl = "https://fs.contoso.com/FederationMetadata/2007-06/FederationMetadata.xml"
try {
    $metadata = Invoke-WebRequest -Uri $metadataUrl -UseBasicParsing
    Write-Output "Metadata accessible. Status: $($metadata.StatusCode). Length: $($metadata.Content.Length)"
} catch {
    Write-Error "Metadata endpoint FAILED: $($_.Exception.Message)"
}

# Verify federation trust (from the AD FS server)
Get-AdfsRelyingPartyTrust | ForEach-Object {
    [PSCustomObject]@{
        Name       = $_.Name
        Enabled    = $_.Enabled
        Identifier = $_.Identifier -join "; "
        Monitoring = $_.MonitoringEnabled
    }
} | Format-Table -AutoSize
```

### Token Debugging

```powershell
# Enable token replay detection logging
Set-AdfsProperties -EnableTokenReplayDetection $true

# View issued tokens (audit log)
Get-WinEvent -LogName "Security" -FilterXPath `
    "*[System[EventID=4624] and EventData[Data[@Name='AuthenticationPackageName']='Negotiate']]" `
    -MaxEvents 20 | Select-Object TimeCreated, @{N='User';E={$_.Properties[5].Value}} | Format-Table

# Test SAML token issuance (from AD FS server)
# Generate a test token for a relying party
$rp = Get-AdfsRelyingPartyTrust -Name "Custom App"
Write-Output "Relying Party: $($rp.Name)"
Write-Output "Identifier: $($rp.Identifier)"
Write-Output "SAML Endpoints: $($rp.SamlEndpoints | ForEach-Object { $_.Location })"
Write-Output "Claim Rules:"
Write-Output $rp.IssuanceTransformRules
```

### Browser Developer Tools for SAML Debugging

```
Step-by-step SAML debugging with browser dev tools:
1. Open browser Dev Tools (F12) → Network tab → check "Preserve log"
2. Navigate to the SP login URL
3. Look for a 302 redirect to the IdP (AD FS / Entra ID login page)
4. After authentication, look for a POST request back to the SP ACS URL
5. In the POST body, find the SAMLResponse parameter
6. Decode the Base64 value:
   - Use browser console: atob("SAMLResponse_value_here")
   - Or PowerShell: [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("..."))
7. Inspect the decoded XML for:
   - StatusCode: Must be "Success"
   - Audience: Must match SP entity ID
   - NameID: Must be the expected format and value
   - NotBefore / NotOnOrAfter: Check for clock skew (> 5 min difference causes failures)
   - Signature: Must be present and valid
```

### Kerberos Debugging

```powershell
# Show all cached Kerberos tickets
klist tickets

# Verify ticket for specific service
klist | Select-String -Pattern "HTTP/webapp.contoso.com"

# Purge tickets and re-test
klist purge
# Then access the service and check again
Invoke-WebRequest -Uri "https://webapp.contoso.com" -UseDefaultCredentials -UseBasicParsing
klist

# Verify SPN exists and is unique
setspn -Q HTTP/webapp.contoso.com
# Expected: "Existing SPN found!" with exactly ONE entry
# If "No such SPN found" → register it
# If multiple entries → duplicate SPN (critical error, must resolve)

# Check SPN on the computer account
setspn -L WEBSERVER01

# Validate time synchronization (Kerberos tolerance is 5 minutes by default)
w32tm /query /status
w32tm /stripchart /computer:dc01.contoso.com /dataonly /samples:3

# Check domain trust relationship
Test-ComputerSecureChannel -Verbose
# If broken:
Test-ComputerSecureChannel -Repair -Credential (Get-Credential)
```

### Entra ID Sign-In Logs

```powershell
Connect-MgGraph -Scopes "AuditLog.Read.All", "Directory.Read.All"

# Query sign-in logs (last 24 hours)
$startDate = (Get-Date).AddHours(-24).ToString("yyyy-MM-ddTHH:mm:ssZ")
$signIns = Get-MgAuditLogSignIn -Filter "createdDateTime ge $startDate" -Top 50 |
    Select-Object CreatedDateTime, UserDisplayName, UserPrincipalName, AppDisplayName,
        @{N='Status';E={$_.Status.ErrorCode}},
        @{N='FailureReason';E={$_.Status.FailureReason}},
        IpAddress, ConditionalAccessStatus

# Filter for failures only
$signIns | Where-Object { $_.Status -ne 0 } | Format-Table -AutoSize

# Common Entra ID sign-in error codes:
# 50011 — Reply URL mismatch (redirect URI not registered)
# 50076 — MFA required but not completed
# 50105 — User not assigned to the application
# 50126 — Invalid username or password
# 50140 — "Keep me signed in" interrupt
# 53003 — Blocked by conditional access
# 65004 — User declined consent
# 70011 — Invalid scope
# 700016 — Application not found in tenant
# 7000218 — Request body must contain client_assertion or client_secret
# AADSTS90056 — Conditional access policy requires compliant device

# Get sign-ins for a specific user
$userSignIns = Get-MgAuditLogSignIn -Filter "userPrincipalName eq 'user@contoso.com'" -Top 20
$userSignIns | Format-Table CreatedDateTime, AppDisplayName,
    @{N='Error';E={$_.Status.ErrorCode}}, @{N='Reason';E={$_.Status.FailureReason}},
    ConditionalAccessStatus -Wrap

# Get sign-ins for a specific application
$appSignIns = Get-MgAuditLogSignIn -Filter "appDisplayName eq 'Contoso HR App'" -Top 20
$appSignIns | Format-List
```

### Common SSO Failures and Resolution

```
┌────────────────────────────────┬──────────────────────────────────────────────────┐
│ Symptom                        │ Resolution                                       │
├────────────────────────────────┼──────────────────────────────────────────────────┤
│ "AADSTS50011: Reply URL does   │ Register the exact redirect URI in app           │
│ not match"                     │ registration (including trailing slash)           │
├────────────────────────────────┼──────────────────────────────────────────────────┤
│ SAML assertion AudienceRestr   │ SP entity ID must exactly match the Identifier   │
│ validation failed              │ in AD FS relying party trust or Entra app        │
├────────────────────────────────┼──────────────────────────────────────────────────┤
│ Clock skew error / NotBefore   │ Sync clocks: w32tm /resync — tolerance is 5 min │
│ / NotOnOrAfter                 │ for Kerberos, configurable for SAML              │
├────────────────────────────────┼──────────────────────────────────────────────────┤
│ Kerberos double-hop failure    │ Configure constrained delegation or RBCD on the  │
│ (access denied on back-end)    │ front-end service account / computer             │
├────────────────────────────────┼──────────────────────────────────────────────────┤
│ "401 Unauthorized" with WIA    │ Check: SPN registered, browser in Intranet zone, │
│                                │ Negotiate provider enabled in IIS                │
├────────────────────────────────┼──────────────────────────────────────────────────┤
│ AD FS login loop (redirects    │ Check token signing cert validity, relying party │
│ back to IdP repeatedly)        │ trust identifier, and cookie/session issues      │
├────────────────────────────────┼──────────────────────────────────────────────────┤
│ Seamless SSO not working       │ Verify AZUREADSSOACC account exists in AD,       │
│                                │ Kerberos key is current, site is in Intranet     │
│                                │ zone, and user is on domain-joined device        │
├────────────────────────────────┼──────────────────────────────────────────────────┤
│ AD Connect sync errors         │ Check: Get-ADSyncRunProfileResult, resolve       │
│                                │ attribute conflicts, verify connector creds      │
├────────────────────────────────┼──────────────────────────────────────────────────┤
│ Conditional access blocks      │ Review Entra sign-in logs → Conditional Access   │
│ unexpectedly                   │ tab, check policy evaluation order, exclude      │
│                                │ break-glass accounts                             │
├────────────────────────────────┼──────────────────────────────────────────────────┤
│ Expired AD FS certificate      │ Rotate immediately: Update-AdfsCertificate       │
│                                │ Restart adfssrv, update all RP trusts with new   │
│                                │ metadata, update WAP servers                     │
└────────────────────────────────┴──────────────────────────────────────────────────┘
```

---

## Related Skills

| Skill | Scope |
|---|---|
| `windows-powershell` | Core PowerShell language, modules, remoting, scripting patterns |
| `windows-ps-server-admin` | AD DS, DNS, DHCP, IIS, Hyper-V, WSUS, AD CS, server roles |
| `windows-ps-security` | Windows Firewall, Defender, BitLocker, audit policy, AppLocker |
| `windows-cmd` | Legacy CMD commands, batch scripting, system utilities |
| `linux-centrify` | Centrify/Delinea on Linux — AD-joined Linux machines in the same SSO infrastructure |
