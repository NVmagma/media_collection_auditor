# Integration setup

Open **Integrations** for the current readiness and copyable API URLs. Configure a
strong `INTEGRATION_API_TOKEN`, title details and optional artwork/coverage flags.
Keep the token private. Use the auditor's host port, normally `8089`, rather than
the container's internal `8080` when accessing it through the Unraid host.

For Homarr choose an HTTP API source, a Base URL such as `http://SERVER:8089`, and
Bearer authentication. Enter the token alone in the credential field. Add a GET
request named `titles` with path `/api/v1/titles/leaving-soon`. Under query values,
add key `library`, literal value `Movies` or `TV`. Do not duplicate `http://` in the
Base URL. Keep the JSX template's expected library consistent with that query.

An empty Holding list is valid. A 401 is an authentication problem; an external
request error may be an incorrect URL or connectivity issue. A 503 indicates
unavailable observations and must not be treated as an empty collection. Test the
API before changing the widget's presentation. See [API contract](integration-api.md)
and [widget examples](integration-widgets.md).
