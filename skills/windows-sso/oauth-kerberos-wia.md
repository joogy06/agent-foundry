# OAuth2/OIDC and Kerberos

Reference file for the `windows-sso` skill. Covers OAuth 2.0/OpenID Connect, Kerberos delegation, Windows Integrated Authentication.

## 4. OAuth 2.0 / OpenID Connect

### Register OAuth Application in AD FS

```powershell
# Register an OAuth2 client (confidential client — server-side app)
Add-AdfsClient -ClientId "contoso-webapp-client" `
    -Name "Contoso Web Application" `
    -RedirectUri "https://app.contoso.com/auth/callback" `
    -Description "OAuth2 client for Contoso web app"

# Generate a client secret
$secret = New-Guid
Add-AdfsClient -ClientId "contoso-api-client" `
    -Name "Contoso API Client" `
    -RedirectUri "https://app.contoso.com/callback" `
    -ClientSecret (ConvertTo-SecureString $secret.ToString() -AsPlainText -Force)

# Register a Web API (resource)
Add-AdfsWebApiApplication -ApplicationGroupId "ContosoAppGroup" `
    -Name "Contoso Web API" `
    -Identifier "https://api.contoso.com" `
    -AccessControlPolicyName "Permit everyone"

# Register a server application (confidential client) in an application group
Add-AdfsServerApplication -ApplicationGroupId "ContosoAppGroup" `
    -Name "Contoso Server App" `
    -Identifier "contoso-server-app" `
    -RedirectUri "https://app.contoso.com/callback" `
    -GenerateClientSecret

# Configure scopes / issuance transform rules for the Web API
$oauthRules = @'
@RuleName = "Issue email claim"
c:[Type == "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"]
=> issue(claim = c);

@RuleName = "Issue UPN as sub"
c:[Type == "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn"]
=> issue(Type = "sub", Value = c.Value);
'@
Set-AdfsWebApiApplication -TargetIdentifier "https://api.contoso.com" `
    -IssuanceTransformRules $oauthRules

# List registered OAuth clients
Get-AdfsClient | Select-Object ClientId, Name, RedirectUri, Enabled | Format-Table -AutoSize

# List application groups
Get-AdfsApplicationGroup | Select-Object Name, Identifier, Enabled
```

### Register OAuth Application in Entra ID

```powershell
# Register app with OAuth2 permissions
$appRegistration = @{
    DisplayName    = "Contoso API Client"
    SignInAudience = "AzureADMyOrg"
    Web = @{
        RedirectUris = @("https://app.contoso.com/auth/callback")
        ImplicitGrantSettings = @{
            EnableAccessTokenIssuance = $false
            EnableIdTokenIssuance     = $true
        }
    }
    RequiredResourceAccess = @(
        @{
            ResourceAppId = "00000003-0000-0000-c000-000000000000"  # Microsoft Graph
            ResourceAccess = @(
                @{ Id = "e1fe6dd8-ba31-4d61-89e7-88639da4683d"; Type = "Scope" },  # User.Read
                @{ Id = "64a6cdd6-aab1-4aaf-94b8-3cc8405e90d0"; Type = "Scope" }   # email
            )
        }
    )
}
$oauthApp = New-MgApplication -BodyParameter $appRegistration

# Create a client secret
$secretParams = @{
    PasswordCredential = @{
        DisplayName = "App Secret"
        EndDateTime = (Get-Date).AddYears(1)
    }
}
$clientSecret = Add-MgApplicationPassword -ApplicationId $oauthApp.Id -BodyParameter $secretParams
Write-Output "Client Secret: $($clientSecret.SecretText)"  # Save this — shown only once

# Define custom API scopes (expose an API)
$apiScopeParams = @{
    IdentifierUris = @("api://$($oauthApp.AppId)")
    Api = @{
        Oauth2PermissionScopes = @(
            @{
                Id                      = (New-Guid)
                AdminConsentDescription = "Access Contoso API"
                AdminConsentDisplayName = "API Access"
                Value                   = "api.read"
                Type                    = "User"
                IsEnabled               = $true
                UserConsentDescription  = "Allow read access to Contoso API"
                UserConsentDisplayName  = "Read API"
            }
        )
    }
}
Update-MgApplication -ApplicationId $oauthApp.Id -BodyParameter $apiScopeParams
```

### OAuth 2.0 Flows Reference

```powershell
# --- Authorization Code Flow (recommended for web apps) ---
# Step 1: Redirect user to authorize endpoint
# GET https://fs.contoso.com/adfs/oauth2/authorize?
#     client_id=contoso-webapp-client
#     &response_type=code
#     &redirect_uri=https://app.contoso.com/auth/callback
#     &scope=openid profile email
#     &state=random_state_value

# Step 2: Exchange authorization code for tokens
$tokenBody = @{
    grant_type    = "authorization_code"
    client_id     = "contoso-webapp-client"
    client_secret = "YOUR_CLIENT_SECRET"
    code          = "AUTHORIZATION_CODE_FROM_CALLBACK"
    redirect_uri  = "https://app.contoso.com/auth/callback"
}
$tokenResponse = Invoke-RestMethod -Method POST `
    -Uri "https://fs.contoso.com/adfs/oauth2/token" `
    -Body $tokenBody -ContentType "application/x-www-form-urlencoded"
$tokenResponse.access_token
$tokenResponse.id_token
$tokenResponse.refresh_token

# --- Client Credentials Flow (service-to-service, no user context) ---
$ccBody = @{
    grant_type    = "client_credentials"
    client_id     = "contoso-api-client"
    client_secret = "YOUR_CLIENT_SECRET"
    scope         = "https://api.contoso.com/.default"
}
$ccToken = Invoke-RestMethod -Method POST `
    -Uri "https://login.microsoftonline.com/TENANT_ID/oauth2/v2.0/token" `
    -Body $ccBody -ContentType "application/x-www-form-urlencoded"

# --- Refresh Token ---
$refreshBody = @{
    grant_type    = "refresh_token"
    client_id     = "contoso-webapp-client"
    client_secret = "YOUR_CLIENT_SECRET"
    refresh_token = $tokenResponse.refresh_token
    scope         = "openid profile email"
}
$newTokens = Invoke-RestMethod -Method POST `
    -Uri "https://fs.contoso.com/adfs/oauth2/token" `
    -Body $refreshBody -ContentType "application/x-www-form-urlencoded"
```

### Token Inspection

```powershell
# Decode a JWT token (ID token or access token) without external tools
function Decode-JWT {
    param([string]$Token)
    $parts = $Token.Split('.')
    $header  = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(($parts[0].Replace('-','+').Replace('_','/').PadRight($parts[0].Length + (4 - $parts[0].Length % 4) % 4, '='))))
    $payload = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(($parts[1].Replace('-','+').Replace('_','/').PadRight($parts[1].Length + (4 - $parts[1].Length % 4) % 4, '='))))
    [PSCustomObject]@{
        Header  = $header | ConvertFrom-Json
        Payload = $payload | ConvertFrom-Json
    }
}

# Usage
$decoded = Decode-JWT -Token $tokenResponse.access_token
$decoded.Header  | Format-List   # alg, typ, kid
$decoded.Payload | Format-List   # iss, sub, aud, exp, iat, claims

# Check token expiration
$exp = $decoded.Payload.exp
$expiryDate = [DateTimeOffset]::FromUnixTimeSeconds($exp).LocalDateTime
Write-Output "Token expires: $expiryDate"

# OIDC discovery endpoint (lists all supported endpoints and capabilities)
Invoke-RestMethod "https://fs.contoso.com/adfs/.well-known/openid-configuration" | Format-List
Invoke-RestMethod "https://login.microsoftonline.com/TENANT_ID/v2.0/.well-known/openid-configuration" | Format-List
```

---

## 5. Kerberos

### Service Principal Names (SPNs)

```powershell
# List SPNs for a service account
setspn -L CONTOSO\svc_webapp

# Query for duplicate SPNs (critical — duplicates break Kerberos)
setspn -Q HTTP/webapp.contoso.com
setspn -X  # Find all duplicate SPNs in the forest

# Register an SPN
setspn -S HTTP/webapp.contoso.com CONTOSO\svc_webapp
setspn -S HTTP/webapp CONTOSO\svc_webapp

# Remove an SPN
setspn -D HTTP/webapp.contoso.com CONTOSO\svc_webapp

# PowerShell alternative
Set-ADUser -Identity svc_webapp -ServicePrincipalNames @{Add="HTTP/webapp.contoso.com"}
Get-ADUser -Identity svc_webapp -Properties ServicePrincipalName | Select-Object -ExpandProperty ServicePrincipalName
```

### Kerberos Delegation

```powershell
# --- Unconstrained Delegation (avoid in production — security risk) ---
# Allows the service to impersonate the user to ANY service
Set-ADComputer -Identity "WEBSERVER01" -TrustedForDelegation $true
# Or for a user account:
Set-ADUser -Identity svc_webapp -TrustedForDelegation $true

# --- Constrained Delegation (recommended) ---
# Allows delegation ONLY to specified SPNs
Set-ADUser -Identity svc_webapp `
    -TrustedForDelegation $false `
    -Add @{'msDS-AllowedToDelegateTo'=@(
        'HTTP/sqlserver.contoso.com',
        'MSSQLSvc/sqlserver.contoso.com:1433'
    )}

# Verify constrained delegation settings
Get-ADUser -Identity svc_webapp -Properties msDS-AllowedToDelegateTo, TrustedForDelegation |
    Select-Object Name, TrustedForDelegation, @{N='DelegationTargets';E={$_.'msDS-AllowedToDelegateTo'}}

# --- Resource-Based Constrained Delegation (RBCD — modern, preferred) ---
# Configured on the TARGET (back-end) server, not the front-end
$frontEnd = Get-ADComputer -Identity "WEBSERVER01"
Set-ADComputer -Identity "SQLSERVER01" `
    -PrincipalsAllowedToDelegateToAccount $frontEnd

# Verify RBCD
Get-ADComputer -Identity "SQLSERVER01" -Properties PrincipalsAllowedToDelegateToAccount |
    Select-Object -ExpandProperty PrincipalsAllowedToDelegateToAccount

# Enable protocol transition (Any authentication → Kerberos) for constrained delegation
Set-ADUser -Identity svc_webapp -Replace @{
    'userAccountControl' = 16842752  # TRUSTED_TO_AUTH_FOR_DELEGATION + NORMAL_ACCOUNT
}
```

### Kerberos Authentication Flow

```
1. User logs into workstation → AS-REQ → Domain Controller
2. DC returns TGT (Ticket Granting Ticket) → AS-REP
3. User accesses web app → TGS-REQ (for HTTP/webapp.contoso.com) → DC
4. DC returns Service Ticket → TGS-REP
5. User sends Service Ticket → Web Server (in Negotiate/SPNEGO header)
6. Web server validates ticket (optionally delegates to back-end via constrained delegation)

Double-Hop Problem:
User → Web Server (Kerberos auth works) → SQL Server (FAILS without delegation)
Solution: Configure constrained or resource-based delegation as shown above
```

### Configure Browsers for Kerberos

```powershell
# --- Internet Explorer / Edge (IE mode): Intranet Zone ---
# GPO: Computer Configuration → Administrative Templates → Windows Components
#       → Internet Explorer → Internet Control Panel → Security Page
# Add sites to Local Intranet zone

# Registry-based (per-machine)
$intranetZone = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings\ZoneMap\Domains\contoso.com"
New-Item -Path $intranetZone -Force
Set-ItemProperty -Path $intranetZone -Name "https" -Value 1  # 1 = Intranet zone
Set-ItemProperty -Path $intranetZone -Name "http" -Value 1

# Enable automatic logon in Intranet zone (required for Kerberos)
# GPO: User Configuration → IE → Security → Local Intranet → Custom → User Authentication
# Or via registry:
Set-ItemProperty -Path "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings\Zones\1" `
    -Name "1A00" -Value 0  # 0 = Automatic logon

# --- Chrome / Edge (Chromium) Policies ---
# GPO or registry: Allow Kerberos negotiation for specific sites
# AuthServerAllowlist — sites allowed for Negotiate authentication
$chromePolicyPath = "HKLM:\SOFTWARE\Policies\Google\Chrome"
New-Item -Path $chromePolicyPath -Force
Set-ItemProperty -Path $chromePolicyPath -Name "AuthServerAllowlist" -Value "*.contoso.com"
Set-ItemProperty -Path $chromePolicyPath -Name "AuthNegotiateDelegateAllowlist" -Value "*.contoso.com"

# Edge (Chromium) equivalent
$edgePolicyPath = "HKLM:\SOFTWARE\Policies\Microsoft\Edge"
New-Item -Path $edgePolicyPath -Force
Set-ItemProperty -Path $edgePolicyPath -Name "AuthServerAllowlist" -Value "*.contoso.com"
Set-ItemProperty -Path $edgePolicyPath -Name "AuthNegotiateDelegateAllowlist" -Value "*.contoso.com"

# Firefox — set via about:config or policies.json
# network.negotiate-auth.trusted-uris = .contoso.com
# network.negotiate-auth.delegation-uris = .contoso.com
```

### Kerberos Debugging

```powershell
# List cached Kerberos tickets
klist

# List tickets for a specific logon session
klist -li 0x3e7  # SYSTEM session

# Purge all Kerberos tickets (force re-authentication)
klist purge

# Check if a service ticket can be obtained
# Use a test connection — if Kerberos works, klist will show the ticket
Invoke-WebRequest -Uri "https://webapp.contoso.com" -UseDefaultCredentials
klist  # Look for HTTP/webapp.contoso.com ticket

# Verify SPN resolution
setspn -Q HTTP/webapp.contoso.com  # Must return exactly ONE result

# Enable Kerberos event logging
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Lsa\Kerberos\Parameters" `
    -Name "LogLevel" -Value 1 -Type DWord

# Check Kerberos-related event logs
Get-WinEvent -LogName "System" -FilterXPath "*[System[Provider[@Name='Microsoft-Windows-Kerberos-Key-Distribution-Center']]]" -MaxEvents 20
Get-WinEvent -LogName "Security" -FilterXPath "*[System[EventID=4768 or EventID=4769 or EventID=4770 or EventID=4771]]" -MaxEvents 20 |
    Select-Object TimeCreated, Id, Message | Format-Table -Wrap
# 4768 = TGT request, 4769 = Service Ticket request, 4770 = TGT renewal, 4771 = Kerberos pre-auth failed
```

---

## 6. Windows Integrated Authentication (WIA / SPNEGO)

### IIS Configuration for Windows Authentication

```powershell
# Install IIS Windows Authentication feature
Install-WindowsFeature -Name Web-Windows-Auth

# Enable Windows Authentication on a site
Import-Module WebAdministration
Set-WebConfigurationProperty -Filter "/system.webServer/security/authentication/windowsAuthentication" `
    -Name "enabled" -Value $true -PSPath "IIS:\Sites\Default Web Site\MyApp"

# Disable Anonymous Authentication (enforce WIA)
Set-WebConfigurationProperty -Filter "/system.webServer/security/authentication/anonymousAuthentication" `
    -Name "enabled" -Value $false -PSPath "IIS:\Sites\Default Web Site\MyApp"

# Configure Negotiate provider order (Kerberos first, NTLM fallback)
# Ensure "Negotiate" is listed before "NTLM" in providers
$site = "IIS:\Sites\Default Web Site\MyApp"
$providers = Get-WebConfigurationProperty -Filter "/system.webServer/security/authentication/windowsAuthentication/providers" `
    -Name "." -PSPath $site
$providers.Collection | Select-Object Value

# Set providers: Negotiate (includes Kerberos) should be first
Remove-WebConfigurationProperty -Filter "/system.webServer/security/authentication/windowsAuthentication/providers" `
    -Name "." -PSPath $site -AtElement @{value="NTLM"}
Remove-WebConfigurationProperty -Filter "/system.webServer/security/authentication/windowsAuthentication/providers" `
    -Name "." -PSPath $site -AtElement @{value="Negotiate"}
Add-WebConfigurationProperty -Filter "/system.webServer/security/authentication/windowsAuthentication/providers" `
    -Name "." -PSPath $site -Value "Negotiate"
Add-WebConfigurationProperty -Filter "/system.webServer/security/authentication/windowsAuthentication/providers" `
    -Name "." -PSPath $site -Value "NTLM"

# Enable Kernel-mode authentication (better performance, required for SPN-less on IIS app pool identity)
Set-WebConfigurationProperty -Filter "/system.webServer/security/authentication/windowsAuthentication" `
    -Name "useKernelMode" -Value $true -PSPath $site

# Configure useAppPoolCredentials (required when app pool runs as domain account with SPN)
Set-WebConfigurationProperty -Filter "/system.webServer/security/authentication/windowsAuthentication" `
    -Name "useAppPoolCredentials" -Value $true -PSPath $site
```

### GPO for Automatic Logon / Intranet Detection

```powershell
# Configure Local Intranet zone auto-detect via GPO (Group Policy Preferences)
# Path: Computer Configuration → Policies → Administrative Templates →
#        Windows Components → Internet Explorer → Internet Control Panel → Security Page
# "Site to Zone Assignment List" — add *.contoso.com = 1 (Intranet)

# Registry equivalent (push via GPO Preferences or script)
$domains = @("contoso.com", "corp.contoso.com", "intranet.contoso.com")
foreach ($domain in $domains) {
    $regPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings\ZoneMap\Domains\$domain"
    New-Item -Path $regPath -Force | Out-Null
    Set-ItemProperty -Path $regPath -Name "https" -Value 1
    Set-ItemProperty -Path $regPath -Name "http" -Value 1
}

# Enable "Automatic logon only in Intranet zone"
Set-ItemProperty -Path "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Internet Settings\Zones\1" `
    -Name "1A00" -Value 0  # 0 = Automatic logon with current username and password
```

### NTLM Fallback and Hardening

```powershell
# Check current NTLM usage
Get-WinEvent -LogName "Microsoft-Windows-NTLM/Operational" -MaxEvents 50 |
    Select-Object TimeCreated, Message | Format-Table -Wrap

# Enable NTLM auditing (identify apps still using NTLM before restricting)
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Lsa\MSV1_0" `
    -Name "AuditReceivingNTLMTraffic" -Value 2  # 2 = Enable auditing for all accounts

# Restrict NTLM usage (after verifying no critical dependencies)
# LmCompatibilityLevel: 5 = Send NTLMv2 only, refuse LM and NTLM
Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Lsa" `
    -Name "LmCompatibilityLevel" -Value 5
```

---

