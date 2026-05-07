# OAuth 2.1 Authentication Spec

## Overview

Authentication uses OAuth 2.1 with mandatory PKCE for all public clients.

## Token Refresh

Refresh tokens expire after 30 days of inactivity. Clients should call /oauth/refresh before expiry to obtain a new access token.

## Rate Limits

The /oauth/token endpoint is limited to 100 requests per minute per client_id.

## Deprecation Notice

The /oauth/legacy endpoint is deprecated and will be removed in v2. New integrations should use /oauth/token instead.

## Open Questions

Should we support refresh-token rotation by default? Currently rotation is opt-in per client.

## Recommendations

Clients are recommended to cache the JWKS for one hour to reduce load on the auth service.

## Caveats

The 30-day expiry applies only when the client checks in at least once per week. Idle clients are revoked after 7 days.
