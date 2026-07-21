# Zoho People Leave Integration

## Tenant and authorization

- Product: Zoho People
- Organization portal: `https://people.zoho.in/solulever/zp`
- Zoho data center: India (`.in`)
- Integration account: `shantanu.singh@solulever.com`
- OAuth client type: Self Client
- OAuth client ID: `1000.PK2TBMKFNQPUV4RXLRBPQOGMNRBS2P`
- OAuth scope: `ZOHOPEOPLE.leave.ALL`
- Accounts endpoint: `https://accounts.zoho.in/oauth/v2/token`
- People API base: `https://people.zoho.in`

The OAuth client secret and refresh token must never be committed to this repository. They are stored only in `/etc/protracklite.env` on production, whose permissions are restricted to `0600`.

The one-time authorization code was exchanged successfully. Zoho issued a refresh token and the production environment contains:

```env
ZOHO_CLIENT_ID=...
ZOHO_CLIENT_SECRET=...
ZOHO_REFRESH_TOKEN=...
ZOHO_ACCOUNTS_URL=https://accounts.zoho.in
ZOHO_PEOPLE_URL=https://people.zoho.in
```

## Current blocker

Token refresh succeeds, but the Zoho People leave-type probe currently returns:

```text
7077 — Sorry! your role is not allowed to access APIs.
```

Enable API access for the integration account in Zoho People:

```text
Settings
→ Manage Accounts
→ User Access Control
→ Function Based Permissions
→ API Access
```

The integration account should be a Super Administrator/Administrator or a Leave Service Administrator with organization-level access. Retest the stored token after enabling the permission; a new authorization code should normally not be required.

## Planned synchronization

After API access is enabled:

1. Fetch Zoho leave types for active employees and map their IDs to ProTrack categories: Planned, Sick, Casual, Unpaid, and Comp Off.
2. Create one Zoho leave request for each ProTrack leave request, not one request per working-day database row.
3. Map full days to a leave count of `1.0`, Half Day AM to `0.5` with session `1`, and Half Day PM to `0.5` with session `2`.
4. Store the returned Zoho leave ID and synchronization status against the ProTrack request group.
5. Update the Zoho request when leave changes and cancel it when the grouped ProTrack leave is removed.
6. Retry transient failures without creating duplicate Zoho records.

Official references:

- [Zoho Self Client authorization flow](https://www.zoho.com/developer/oauth/self-client/authorization-code-flow.html)
- [Zoho People OAuth scopes](https://www.zoho.com/people/api/v3/scopes.html)
- [Add Leave Request API v3](https://www.zoho.com/people/api/v3/leave-tracker/add-leave.html)
- [Edit Leave Request API v3](https://www.zoho.com/people/api/v3/leave-tracker/edit-leave.html)
- [Cancel Leave API](https://www.zoho.com/people/api/cancel-leave.html)
