# AD FS, Azure AD, and SAML

Reference file for the `windows-sso` skill. Covers AD FS configuration, Azure AD/Entra ID SSO, SAML 2.0 implementation.

## 1. Active Directory Federation Services (AD FS)

### Install AD FS Role

```powershell
# Install AD FS role with management tools
Install-WindowsFeature -Name ADFS-Federation -IncludeManagementTools

# Verify installation
Get-WindowsFeature -Name ADFS-Federation | Select-Object Name, Installed, InstallState
```

### Initial AD FS Configuration (First Server in Farm)

```powershell
# Import the SSL certificate (wildcard or SAN cert for federation service name)
$certPassword = Read-Host -AsSecureString -Prompt "PFX password"
Import-PfxCertificate -FilePath "C:\Certs\adfs-ssl.pfx" `
    -CertStoreLocation Cert:\LocalMachine\My -Password $certPassword

# Get the certificate thumbprint
$sslThumbprint = (Get-ChildItem -Path Cert:\LocalMachine\My |
    Where-Object { $_.Subject -like "*fs.contoso.com*" }).Thumbprint

# Create a gMSA (Group Managed Service Account) for AD FS
# First, ensure the KDS root key exists (one-time, domain-wide)
Add-KdsRootKey -EffectiveImmediately  # For lab; production: Add-KdsRootKey -EffectiveTime ((Get-Date).AddHours(-10))

# Create the gMSA
New-ADServiceAccount -Name "svc_adfs" `
    -DNSHostName "fs.contoso.com" `
    -PrincipalsAllowedToRetrieveManagedPassword "ADFS-Servers$" `
    -ServicePrincipalNames "http/fs.contoso.com"

# Configure the first AD FS server in a new farm
Install-AdfsFarm `
    -CertificateThumbprint $sslThumbprint `
    -FederationServiceName "fs.contoso.com" `
    -FederationServiceDisplayName "Contoso Federation Service" `
    -GroupServiceAccountIdentifier "CONTOSO\svc_adfs$" `
    -OverwriteConfiguration
```

### Add Server to Existing AD FS Farm

```powershell
# On the secondary server, join the existing farm
Install-WindowsFeature -Name ADFS-Federation -IncludeManagementTools
Add-AdfsFarmNode `
    -CertificateThumbprint $sslThumbprint `
    -GroupServiceAccountIdentifier "CONTOSO\svc_adfs$" `
    -PrimaryComputerName "ADFS01.contoso.com" `
    -PrimaryComputerPort 80 `
    -OverwriteConfiguration
```

### AD FS Properties and Configuration

```powershell
# View all AD FS properties
Get-AdfsProperties

# Key properties to inspect
Get-AdfsProperties | Select-Object HostName, Identifier, FederationPassiveAddress,
    IdTokenIssuer, TokenLifetime, SSOLifetime, AutoCertificateRollover

# Set SSO lifetime (in minutes, default 480 = 8 hours)
Set-AdfsProperties -SSOLifetime 480

# Enable Keep Me Signed In (KMSI)
Set-AdfsProperties -EnableKmsi $true -KmsiLifetimeMins 10080  # 7 days

# Set token lifetime
Set-AdfsProperties -TokenLifetime 60  # minutes

# Enable WIA for additional user agents (e.g., Chrome, Edge)
Set-AdfsProperties -WIASupportedUserAgents @(
    "MSAuthHost/1.0",
    "MSIE 6.0", "MSIE 7.0", "MSIE 8.0", "MSIE 9.0", "MSIE 10.0",
    "Trident/7.0", "MSIPC", "Windows Rights Management Client",
    "Mozilla/5.0", "Edge/", "Chrome/"
)
```

### Relying Party Trusts

```powershell
# Add relying party trust via federation metadata URL
Add-AdfsRelyingPartyTrust `
    -Name "Salesforce" `
    -MetadataUrl "https://login.salesforce.com/saml/metadata/xxxxx" `
    -IssuanceTransformRules $null `
    -AccessControlPolicyName "Permit everyone"

# Add relying party trust manually (no metadata)
Add-AdfsRelyingPartyTrust `
    -Name "Custom App" `
    -Identifier "https://app.contoso.com" `
    -SamlEndpoint (New-AdfsSamlEndpoint -Binding POST `
        -Protocol SAMLAssertionConsumer `
        -Uri "https://app.contoso.com/saml/acs") `
    -AccessControlPolicyName "Permit everyone"

# List all relying party trusts
Get-AdfsRelyingPartyTrust | Select-Object Name, Identifier, Enabled,
    MonitoringEnabled, IssuanceTransformRules | Format-List

# Get specific trust details
Get-AdfsRelyingPartyTrust -Name "Salesforce" | Format-List *

# Enable/disable a trust
Set-AdfsRelyingPartyTrust -TargetName "Custom App" -Enabled $true
Disable-AdfsRelyingPartyTrust -TargetName "Custom App"

# Update metadata for a trust
Update-AdfsRelyingPartyTrust -TargetName "Salesforce"

# Remove a trust
Remove-AdfsRelyingPartyTrust -TargetName "Old App"
```

### Claims Issuance Transform Rules

```powershell
# Define issuance transform rules (claim rules language)
$rules = @'
@RuleTemplate = "LdapClaims"
@RuleName = "Send LDAP Attributes as Claims"
c:[Type == "http://schemas.microsoft.com/ws/2008/06/identity/claims/windowsaccountname",
   Issuer == "AD AUTHORITY"]
=> issue(store = "Active Directory",
         types = ("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
                  "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname",
                  "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname",
                  "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn",
                  "http://schemas.xmlsoap.org/claims/Group"),
         query = ";mail,givenName,sn,userPrincipalName,tokenGroups(domainQualifiedName);{0}",
         param = c.Value);

@RuleTemplate = "PassThroughClaims"
@RuleName = "Pass Through UPN as NameID"
c:[Type == "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn"]
=> issue(Type = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier",
         Issuer = c.Issuer,
         OriginalIssuer = c.OriginalIssuer,
         Value = c.Value,
         ValueType = c.ValueType,
         Properties["http://schemas.xmlsoap.org/ws/2005/05/identity/claimproperties/format"]
             = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress");
'@

# Apply claim rules to a relying party trust
Set-AdfsRelyingPartyTrust -TargetName "Custom App" -IssuanceTransformRules $rules

# View current rules for a trust
(Get-AdfsRelyingPartyTrust -Name "Custom App").IssuanceTransformRules

# Add issuance authorization rules (who can access)
$authRules = @'
@RuleTemplate = "AllowAllAuthzRule"
=> issue(Type = "http://schemas.microsoft.com/authorization/claims/permit",
         Value = "true");
'@
Set-AdfsRelyingPartyTrust -TargetName "Custom App" -IssuanceAuthorizationRules $authRules

# Restrict access to a specific group
$restrictedAuthRules = @'
@RuleTemplate = "Authorization"
@RuleName = "Permit SSO-Users group"
c:[Type == "http://schemas.xmlsoap.org/claims/Group", Value == "CONTOSO\SSO-Users"]
=> issue(Type = "http://schemas.microsoft.com/authorization/claims/permit",
         Value = "PermitUsersWithClaim");
'@
Set-AdfsRelyingPartyTrust -TargetName "Custom App" -IssuanceAuthorizationRules $restrictedAuthRules
```

### AD FS Claim Descriptions

```powershell
# List all registered claim descriptions
Get-AdfsClaimDescription | Select-Object Name, ClaimType, ShortName | Format-Table -AutoSize

# Add a custom claim description
Add-AdfsClaimDescription `
    -Name "Employee ID" `
    -ClaimType "http://schemas.contoso.com/claims/employeeid" `
    -ShortName "employeeid" `
    -IsAccepted $true -IsOffered $true -IsRequired $false
```

### AD FS Certificate Management

```powershell
# List all AD FS certificates
Get-AdfsCertificate | Format-Table CertificateType, Thumbprint, IsPrimary,
    @{N='Subject';E={$_.Certificate.Subject}},
    @{N='NotAfter';E={$_.Certificate.NotAfter}} -AutoSize

# Add a new token signing certificate (set as secondary first, then promote)
Add-AdfsCertificate -CertificateType Token-Signing -Thumbprint "NEWTHUMBPRINT"
Set-AdfsCertificate -CertificateType Token-Signing -Thumbprint "NEWTHUMBPRINT" -IsPrimary

# Update SSL certificate
Set-AdfsSslCertificate -Thumbprint "NEWSSLTHUMBPRINT"
# Must also update the HTTPS binding
netsh http delete sslcert hostnameport=fs.contoso.com:443
netsh http add sslcert hostnameport=fs.contoso.com:443 certhash=NEWSSLTHUMBPRINT appid="{5d89a20c-beab-4389-9447-324788eb944a}" certstorename=MY

# Restart AD FS after cert changes
Restart-Service adfssrv
```

### AD FS Endpoints

```powershell
# List all endpoints and their status
Get-AdfsEndpoint | Select-Object FullUrl, Protocol, Enabled, Proxy | Format-Table -AutoSize

# Enable/disable specific endpoints
Enable-AdfsEndpoint -TargetAddressPath "/adfs/services/trust/13/windowstransport"
Disable-AdfsEndpoint -TargetAddressPath "/adfs/services/trust/2005/windowstransport"

# Key AD FS endpoint URLs:
# Federation metadata:  https://fs.contoso.com/FederationMetadata/2007-06/FederationMetadata.xml
# SAML 2.0 POST:        https://fs.contoso.com/adfs/ls/
# WS-Federation:        https://fs.contoso.com/adfs/ls/
# OAuth2 authorize:     https://fs.contoso.com/adfs/oauth2/authorize
# OAuth2 token:         https://fs.contoso.com/adfs/oauth2/token
# OIDC discovery:       https://fs.contoso.com/adfs/.well-known/openid-configuration
```

---

## 2. Azure AD / Entra ID SSO

### Enterprise Application Registration (SAML SSO)

```powershell
# Install Microsoft Graph PowerShell module
Install-Module Microsoft.Graph -Scope CurrentUser
Connect-MgGraph -Scopes "Application.ReadWrite.All", "Directory.ReadWrite.All"

# Create an enterprise application (service principal) from gallery template
# First, find the template
$template = Get-MgServicePrincipal -Filter "displayName eq 'Salesforce'" -Top 1

# Create a new application registration
$appParams = @{
    DisplayName = "Contoso Custom App"
    SignInAudience = "AzureADMyOrg"
    Web = @{
        RedirectUris = @("https://app.contoso.com/auth/callback")
    }
    RequiredResourceAccess = @(
        @{
            ResourceAppId = "00000003-0000-0000-c000-000000000000"  # Microsoft Graph
            ResourceAccess = @(
                @{ Id = "e1fe6dd8-ba31-4d61-89e7-88639da4683d"; Type = "Scope" }  # User.Read
            )
        }
    )
}
$app = New-MgApplication -BodyParameter $appParams

# Create corresponding service principal
$sp = New-MgServicePrincipal -AppId $app.AppId

# Configure SAML SSO for the enterprise app
$samlParams = @{
    PreferredSingleSignOnMode = "saml"
    SamlSingleSignOnSettings = @{
        RelayState = ""
    }
}
Update-MgServicePrincipal -ServicePrincipalId $sp.Id -BodyParameter $samlParams
```

### Configure SAML Settings in Entra ID

```powershell
# Set SAML SSO URLs for the application
$samlUrls = @{
    LoginUrl           = "https://app.contoso.com/saml/login"
    LogoutUrl          = "https://app.contoso.com/saml/logout"
    ReplyUrls          = @("https://app.contoso.com/saml/acs")
}
Update-MgApplication -ApplicationId $app.Id -Web $samlUrls

# Set identifier URIs
Update-MgApplication -ApplicationId $app.Id -IdentifierUris @("https://app.contoso.com")

# Configure attribute mapping / claims mapping policy
$claimsPolicy = @{
    Definition = @(
        '{"ClaimsMappingPolicy":{"Version":1,"IncludeBasicClaimSet":"true","ClaimsSchema":[{"Source":"user","ID":"userprincipalname","SamlClaimType":"http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier"},{"Source":"user","ID":"mail","SamlClaimType":"http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"},{"Source":"user","ID":"displayname","SamlClaimType":"http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"},{"Source":"user","ID":"givenname","SamlClaimType":"http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname"},{"Source":"user","ID":"surname","SamlClaimType":"http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname"}]}}'
    )
    DisplayName  = "Contoso Claims Policy"
    IsOrganizationDefault = $false
}
$policy = New-MgPolicyClaimsMappingPolicy -BodyParameter $claimsPolicy

# Assign the claims mapping policy to the service principal
New-MgServicePrincipalClaimsMappingPolicyByRef -ServicePrincipalId $sp.Id -OdataId "https://graph.microsoft.com/v1.0/policies/claimsMappingPolicies/$($policy.Id)"
```

### User and Group Assignment

```powershell
# Assign a user to the enterprise app
$assignment = @{
    PrincipalId  = "USER-OBJECT-ID"
    ResourceId   = $sp.Id
    AppRoleId    = "00000000-0000-0000-0000-000000000000"  # default role
}
New-MgServicePrincipalAppRoleAssignedTo -ServicePrincipalId $sp.Id -BodyParameter $assignment

# Assign a group
$groupAssignment = @{
    PrincipalId  = "GROUP-OBJECT-ID"
    ResourceId   = $sp.Id
    AppRoleId    = "00000000-0000-0000-0000-000000000000"
}
New-MgServicePrincipalAppRoleAssignedTo -ServicePrincipalId $sp.Id -BodyParameter $groupAssignment

# List current assignments
Get-MgServicePrincipalAppRoleAssignedTo -ServicePrincipalId $sp.Id |
    Select-Object PrincipalDisplayName, PrincipalType, AppRoleId

# Require user assignment (non-assigned users cannot access)
Update-MgServicePrincipal -ServicePrincipalId $sp.Id -AppRoleAssignmentRequired:$true
```

### SSO Modes Overview

```powershell
# Check current SSO mode for an enterprise app
Get-MgServicePrincipal -ServicePrincipalId $sp.Id |
    Select-Object DisplayName, PreferredSingleSignOnMode, LoginUrl

# SSO Modes available in Entra ID:
# - saml            : SAML 2.0-based SSO (most enterprise apps)
# - oidc            : OpenID Connect / OAuth 2.0 (modern apps)
# - password         : Password vaulting (Entra ID stores and replays credentials)
# - linked          : Link to existing SSO URL (no Entra ID SSO processing)
# - notSupported    : App does not support SSO through Entra ID

# Set SSO mode
Update-MgServicePrincipal -ServicePrincipalId $sp.Id -PreferredSingleSignOnMode "saml"
```

### Azure AD Connect Seamless SSO

```powershell
# Enable Seamless SSO during Azure AD Connect setup (PowerShell method)
# Run on the AD Connect server
Import-Module "C:\Program Files\Microsoft Azure Active Directory Connect\AzureADSSO.psd1"
New-AzureADSSOAuthenticationContext

# Enable Seamless SSO for your AD forest
Enable-AzureADSSOForest -OnPremCredentials (Get-Credential -Message "Enter Domain Admin credentials")

# Verify Seamless SSO status
Get-AzureADSSOStatus | ConvertFrom-Json

# The AZUREADSSOACC computer account is created in AD — verify it exists
Get-ADComputer -Identity "AZUREADSSOACC" -Properties PasswordLastSet, ServicePrincipalName |
    Select-Object Name, PasswordLastSet, ServicePrincipalName

# Roll over the Kerberos decryption key (recommended every 30 days)
Update-AzureADSSOForest -OnPremCredentials (Get-Credential)
```

---

## 3. SAML 2.0

### SP-Initiated vs IdP-Initiated Flows

```
SP-Initiated Flow (most common):
1. User visits app (SP) → 2. SP generates AuthnRequest → 3. Browser redirects to IdP (AD FS / Entra ID)
→ 4. User authenticates → 5. IdP creates SAML Response with Assertion → 6. Browser POSTs to SP ACS URL
→ 7. SP validates assertion → 8. User logged in

IdP-Initiated Flow:
1. User visits IdP portal → 2. Selects target app → 3. IdP creates unsolicited SAML Response
→ 4. Browser POSTs to SP ACS URL → 5. SP validates → 6. User logged in
```

### AD FS SAML Metadata Exchange

```powershell
# AD FS publishes its metadata at:
# https://fs.contoso.com/FederationMetadata/2007-06/FederationMetadata.xml

# Download IdP metadata programmatically
Invoke-WebRequest -Uri "https://fs.contoso.com/FederationMetadata/2007-06/FederationMetadata.xml" `
    -OutFile "C:\Temp\adfs-metadata.xml"

# Import SP metadata when creating a relying party trust
Add-AdfsRelyingPartyTrust -Name "ServiceNow" `
    -MetadataFile "C:\Temp\servicenow-sp-metadata.xml"

# Export AD FS token signing certificate for SP manual configuration
Get-AdfsCertificate -CertificateType Token-Signing | Where-Object { $_.IsPrimary } |
    ForEach-Object {
        $bytes = $_.Certificate.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert)
        [System.IO.File]::WriteAllBytes("C:\Temp\adfs-signing-cert.cer", $bytes)
    }
```

### SAML Assertion Structure (Key Elements)

```xml
<!-- Key elements in a SAML 2.0 Response -->
<samlp:Response Destination="https://app.contoso.com/saml/acs"
                ID="_response123" IssueInstant="2026-03-24T10:00:00Z">
    <saml:Issuer>http://fs.contoso.com/adfs/services/trust</saml:Issuer>
    <samlp:Status>
        <samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/>
    </samlp:Status>
    <saml:Assertion ID="_assertion456" IssueInstant="2026-03-24T10:00:00Z">
        <saml:Issuer>http://fs.contoso.com/adfs/services/trust</saml:Issuer>
        <ds:Signature><!-- XML Signature --></ds:Signature>
        <saml:Subject>
            <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">
                user@contoso.com
            </saml:NameID>
            <saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
                <saml:SubjectConfirmationData
                    NotOnOrAfter="2026-03-24T10:05:00Z"
                    Recipient="https://app.contoso.com/saml/acs"/>
            </saml:SubjectConfirmation>
        </saml:Subject>
        <saml:Conditions NotBefore="2026-03-24T09:59:00Z" NotOnOrAfter="2026-03-24T11:00:00Z">
            <saml:AudienceRestriction>
                <saml:Audience>https://app.contoso.com</saml:Audience>
            </saml:AudienceRestriction>
        </saml:Conditions>
        <saml:AttributeStatement>
            <saml:Attribute Name="http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress">
                <saml:AttributeValue>user@contoso.com</saml:AttributeValue>
            </saml:Attribute>
        </saml:AttributeStatement>
        <saml:AuthnStatement AuthnInstant="2026-03-24T10:00:00Z">
            <saml:AuthnContext>
                <saml:AuthnContextClassRef>
                    urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport
                </saml:AuthnContextClassRef>
            </saml:AuthnContext>
        </saml:AuthnStatement>
    </saml:Assertion>
</samlp:Response>
```

### SAML Bindings Configuration

```powershell
# Configure SAML endpoints with specific bindings on a relying party trust
# HTTP-POST binding (most common for ACS)
$postEndpoint = New-AdfsSamlEndpoint -Binding POST `
    -Protocol SAMLAssertionConsumer -Uri "https://app.contoso.com/saml/acs" -Index 0 -IsDefault $true

# HTTP-Redirect binding (used for AuthnRequest / LogoutRequest)
$redirectEndpoint = New-AdfsSamlEndpoint -Binding Redirect `
    -Protocol SAMLLogout -Uri "https://app.contoso.com/saml/slo"

# HTTP-Artifact binding (for environments requiring backend channel resolution)
$artifactEndpoint = New-AdfsSamlEndpoint -Binding Artifact `
    -Protocol SAMLAssertionConsumer -Uri "https://app.contoso.com/saml/artifact" -Index 1

# Apply endpoints to the relying party trust
Set-AdfsRelyingPartyTrust -TargetName "Custom App" `
    -SamlEndpoint @($postEndpoint, $redirectEndpoint, $artifactEndpoint)
```

### Testing SAML with Browser Tools

```
SAML debugging workflow:
1. Install browser extension "SAML-tracer" (Firefox) or "SAML DevTools" (Chrome)
2. Navigate to the SP-initiated login URL
3. Capture the AuthnRequest (outbound redirect to IdP)
4. Capture the SAML Response (POST back to SP ACS)
5. Decode the Base64 SAML assertion and verify:
   - Issuer matches expected IdP entity ID
   - AudienceRestriction matches SP entity ID
   - NameID format and value are correct
   - NotBefore / NotOnOrAfter timestamps are valid (check clock skew)
   - Signature is present and certificate matches
   - Destination matches the ACS URL

# Decode SAML response from Base64 (PowerShell)
$base64Response = "PHNhbWxwOl..."  # from browser capture
$decodedXml = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($base64Response))
([xml]$decodedXml).Save("C:\Temp\decoded-saml-response.xml")
```

---

