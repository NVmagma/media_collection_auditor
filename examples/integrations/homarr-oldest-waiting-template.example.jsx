<Stack gap="xs">
  <Text fw={700}>10 oldest waiting</Text>
  <Text size="sm">Tracking records; freshness unverified. Dates are local wall time.</Text>
  {status.titles?.loading ? (
    <Text>Refreshing titles...</Text>
  ) : !status.titles?.ok || data.titles?.schema_version !== 1 || data.titles?.status !== "advisory_only" || data.titles?.view !== "oldest-waiting" || !data.titles?.items ? (
    <Text>Title list unavailable</Text>
  ) : data.titles.items.length === 0 ? (
    <Text>No matching tracking records</Text>
  ) : (
    <Stack gap="xs">
      {data.titles.items[0] ? (
        <Stack gap="xs" style={{ border: "1px solid #666", borderRadius: "12px", padding: "10px" }}>
          <Text fw={700}>1. {data.titles.items[0].title}</Text>
          <Text size="sm">{data.titles.items[0].library} · {data.titles.items[0].stage}</Text>
          <Text size="sm">Waiting since: {data.titles.items[0].since ?? "Unknown"}</Text>
        </Stack>
      ) : null}
      {data.titles.items[1] ? (
        <Stack gap="xs" style={{ border: "1px solid #666", borderRadius: "12px", padding: "10px" }}>
          <Text fw={700}>2. {data.titles.items[1].title}</Text>
          <Text size="sm">{data.titles.items[1].library} · {data.titles.items[1].stage}</Text>
          <Text size="sm">Waiting since: {data.titles.items[1].since ?? "Unknown"}</Text>
        </Stack>
      ) : null}
      {data.titles.items[2] ? (
        <Stack gap="xs" style={{ border: "1px solid #666", borderRadius: "12px", padding: "10px" }}>
          <Text fw={700}>3. {data.titles.items[2].title}</Text>
          <Text size="sm">{data.titles.items[2].library} · {data.titles.items[2].stage}</Text>
          <Text size="sm">Waiting since: {data.titles.items[2].since ?? "Unknown"}</Text>
        </Stack>
      ) : null}
      {data.titles.items[3] ? (
        <Stack gap="xs" style={{ border: "1px solid #666", borderRadius: "12px", padding: "10px" }}>
          <Text fw={700}>4. {data.titles.items[3].title}</Text>
          <Text size="sm">{data.titles.items[3].library} · {data.titles.items[3].stage}</Text>
          <Text size="sm">Waiting since: {data.titles.items[3].since ?? "Unknown"}</Text>
        </Stack>
      ) : null}
      {data.titles.items[4] ? (
        <Stack gap="xs" style={{ border: "1px solid #666", borderRadius: "12px", padding: "10px" }}>
          <Text fw={700}>5. {data.titles.items[4].title}</Text>
          <Text size="sm">{data.titles.items[4].library} · {data.titles.items[4].stage}</Text>
          <Text size="sm">Waiting since: {data.titles.items[4].since ?? "Unknown"}</Text>
        </Stack>
      ) : null}
      {data.titles.items[5] ? (
        <Stack gap="xs" style={{ border: "1px solid #666", borderRadius: "12px", padding: "10px" }}>
          <Text fw={700}>6. {data.titles.items[5].title}</Text>
          <Text size="sm">{data.titles.items[5].library} · {data.titles.items[5].stage}</Text>
          <Text size="sm">Waiting since: {data.titles.items[5].since ?? "Unknown"}</Text>
        </Stack>
      ) : null}
      {data.titles.items[6] ? (
        <Stack gap="xs" style={{ border: "1px solid #666", borderRadius: "12px", padding: "10px" }}>
          <Text fw={700}>7. {data.titles.items[6].title}</Text>
          <Text size="sm">{data.titles.items[6].library} · {data.titles.items[6].stage}</Text>
          <Text size="sm">Waiting since: {data.titles.items[6].since ?? "Unknown"}</Text>
        </Stack>
      ) : null}
      {data.titles.items[7] ? (
        <Stack gap="xs" style={{ border: "1px solid #666", borderRadius: "12px", padding: "10px" }}>
          <Text fw={700}>8. {data.titles.items[7].title}</Text>
          <Text size="sm">{data.titles.items[7].library} · {data.titles.items[7].stage}</Text>
          <Text size="sm">Waiting since: {data.titles.items[7].since ?? "Unknown"}</Text>
        </Stack>
      ) : null}
      {data.titles.items[8] ? (
        <Stack gap="xs" style={{ border: "1px solid #666", borderRadius: "12px", padding: "10px" }}>
          <Text fw={700}>9. {data.titles.items[8].title}</Text>
          <Text size="sm">{data.titles.items[8].library} · {data.titles.items[8].stage}</Text>
          <Text size="sm">Waiting since: {data.titles.items[8].since ?? "Unknown"}</Text>
        </Stack>
      ) : null}
      {data.titles.items[9] ? (
        <Stack gap="xs" style={{ border: "1px solid #666", borderRadius: "12px", padding: "10px" }}>
          <Text fw={700}>10. {data.titles.items[9].title}</Text>
          <Text size="sm">{data.titles.items[9].library} · {data.titles.items[9].stage}</Text>
          <Text size="sm">Waiting since: {data.titles.items[9].since ?? "Unknown"}</Text>
        </Stack>
      ) : null}
      {data.titles.truncated ? <Text size="sm">Showing 10 of {data.titles.total_records} tracking records.</Text> : null}
    </Stack>
  )}
</Stack>
