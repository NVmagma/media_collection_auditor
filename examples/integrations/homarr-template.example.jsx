<Stack>
  <Text fw={700}>Auditor tracking records</Text>
  <Text size="sm">Freshness unverified; counts are tracking records.</Text>
  {status.summary?.loading ? (
    <Text>Refreshing tracking records...</Text>
  ) : !status.summary?.ok || data.summary?.schema_version !== 1 || data.summary?.status !== "advisory_only" || !data.summary?.tracking_counts ? (
    <Text>Tracking records unavailable</Text>
  ) : (
    <Stack gap="xs">
      <Text>Waiting: {data.summary.tracking_counts.waiting ?? "Unavailable"}</Text>
      <Text>Holding: {data.summary.tracking_counts.holding ?? "Unavailable"}</Text>
      <Text>Keep: {data.summary.tracking_counts.keep ?? "Unavailable"}</Text>
      <Text>Removal: {data.summary.tracking_counts.removal ?? "Unavailable"}</Text>
      <Text>Arr pending: {data.summary.tracking_counts.arr_sync_pending ?? "Unavailable"}</Text>
    </Stack>
  )}
  {status.audit?.loading ? (
    <Text>Refreshing coordinator status...</Text>
  ) : !status.audit?.ok || data.audit?.schema_version !== 1 || data.audit?.status !== "advisory_only" ? (
    <Text>Coordinator status unavailable</Text>
  ) : (
    <Stack gap="xs">
      <Text>Running: {data.audit.running === true ? "Yes" : data.audit.running === false ? "No" : "Unknown"}</Text>
      <Text>Queued: {data.audit.queued === true ? "Yes" : data.audit.queued === false ? "No" : "Unknown"}</Text>
      <Text>Rescue active: {data.audit.rescuing === true ? "Yes" : data.audit.rescuing === false ? "No" : "Unknown"}</Text>
      <Text>Last recorded result: {data.audit.last_result ?? "Unknown"}</Text>
    </Stack>
  )}
</Stack>
