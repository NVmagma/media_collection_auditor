<Stack gap="xs">
  <Text fw={700}>Leaving soon</Text>
  <Text size="sm">Tracking records; freshness unverified. Dates are local wall time.</Text>
  <Text size="sm">Estimates only. Protections and safety checks can prevent moves; these are not deletion dates.</Text>
  {status.titles?.loading ? (
    <Text>Refreshing titles...</Text>
  ) : !status.titles?.ok || data.titles?.schema_version !== 1 || data.titles?.status !== "advisory_only" || data.titles?.view !== "leaving-soon" || !data.titles?.items ? (
    <Text>Title list unavailable</Text>
  ) : data.titles.items.length === 0 ? (
    <Text>No matching tracking records</Text>
  ) : (
    <Stack gap="xs">
      {data.titles.items[0] ? (
        <Group wrap="nowrap" align="flex-start" gap="sm" style={{ border: "1px solid #666", borderRadius: "12px", padding: "8px" }}>
          {data.titles.items[0].poster_url ? (
            data.titles.items[0].jellyfin_url ? <Anchor href={data.titles.items[0].jellyfin_url} target="_blank" aria-label={data.titles.items[0].title}><Image src={data.titles.items[0].poster_url} alt={data.titles.items[0].title} w={44} h={66} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[0].poster_url} alt={data.titles.items[0].title} w={44} h={66} fit="cover" radius="sm" />
          ) : <Text size="xs" w={44}>No poster</Text>}
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text fw={700}>1. {data.titles.items[0].title}</Text>
            <Text size="sm">{data.titles.items[0].library} · {data.titles.items[0].stage}</Text>
            <Text size="sm">Estimated Holding → Removal: {data.titles.items[0].estimated_removal_stage_at ?? "Unknown"}</Text>
            {data.titles.items[0].jellyfin_url ? <Anchor size="xs" href={data.titles.items[0].jellyfin_url} target="_blank">Open in Jellyfin</Anchor> : <Text size="xs">Jellyfin match unavailable</Text>}
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[1] ? (
        <Group wrap="nowrap" align="flex-start" gap="sm" style={{ border: "1px solid #666", borderRadius: "12px", padding: "8px" }}>
          {data.titles.items[1].poster_url ? (
            data.titles.items[1].jellyfin_url ? <Anchor href={data.titles.items[1].jellyfin_url} target="_blank" aria-label={data.titles.items[1].title}><Image src={data.titles.items[1].poster_url} alt={data.titles.items[1].title} w={44} h={66} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[1].poster_url} alt={data.titles.items[1].title} w={44} h={66} fit="cover" radius="sm" />
          ) : <Text size="xs" w={44}>No poster</Text>}
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text fw={700}>2. {data.titles.items[1].title}</Text>
            <Text size="sm">{data.titles.items[1].library} · {data.titles.items[1].stage}</Text>
            <Text size="sm">Estimated Holding → Removal: {data.titles.items[1].estimated_removal_stage_at ?? "Unknown"}</Text>
            {data.titles.items[1].jellyfin_url ? <Anchor size="xs" href={data.titles.items[1].jellyfin_url} target="_blank">Open in Jellyfin</Anchor> : <Text size="xs">Jellyfin match unavailable</Text>}
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[2] ? (
        <Group wrap="nowrap" align="flex-start" gap="sm" style={{ border: "1px solid #666", borderRadius: "12px", padding: "8px" }}>
          {data.titles.items[2].poster_url ? (
            data.titles.items[2].jellyfin_url ? <Anchor href={data.titles.items[2].jellyfin_url} target="_blank" aria-label={data.titles.items[2].title}><Image src={data.titles.items[2].poster_url} alt={data.titles.items[2].title} w={44} h={66} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[2].poster_url} alt={data.titles.items[2].title} w={44} h={66} fit="cover" radius="sm" />
          ) : <Text size="xs" w={44}>No poster</Text>}
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text fw={700}>3. {data.titles.items[2].title}</Text>
            <Text size="sm">{data.titles.items[2].library} · {data.titles.items[2].stage}</Text>
            <Text size="sm">Estimated Holding → Removal: {data.titles.items[2].estimated_removal_stage_at ?? "Unknown"}</Text>
            {data.titles.items[2].jellyfin_url ? <Anchor size="xs" href={data.titles.items[2].jellyfin_url} target="_blank">Open in Jellyfin</Anchor> : <Text size="xs">Jellyfin match unavailable</Text>}
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[3] ? (
        <Group wrap="nowrap" align="flex-start" gap="sm" style={{ border: "1px solid #666", borderRadius: "12px", padding: "8px" }}>
          {data.titles.items[3].poster_url ? (
            data.titles.items[3].jellyfin_url ? <Anchor href={data.titles.items[3].jellyfin_url} target="_blank" aria-label={data.titles.items[3].title}><Image src={data.titles.items[3].poster_url} alt={data.titles.items[3].title} w={44} h={66} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[3].poster_url} alt={data.titles.items[3].title} w={44} h={66} fit="cover" radius="sm" />
          ) : <Text size="xs" w={44}>No poster</Text>}
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text fw={700}>4. {data.titles.items[3].title}</Text>
            <Text size="sm">{data.titles.items[3].library} · {data.titles.items[3].stage}</Text>
            <Text size="sm">Estimated Holding → Removal: {data.titles.items[3].estimated_removal_stage_at ?? "Unknown"}</Text>
            {data.titles.items[3].jellyfin_url ? <Anchor size="xs" href={data.titles.items[3].jellyfin_url} target="_blank">Open in Jellyfin</Anchor> : <Text size="xs">Jellyfin match unavailable</Text>}
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[4] ? (
        <Group wrap="nowrap" align="flex-start" gap="sm" style={{ border: "1px solid #666", borderRadius: "12px", padding: "8px" }}>
          {data.titles.items[4].poster_url ? (
            data.titles.items[4].jellyfin_url ? <Anchor href={data.titles.items[4].jellyfin_url} target="_blank" aria-label={data.titles.items[4].title}><Image src={data.titles.items[4].poster_url} alt={data.titles.items[4].title} w={44} h={66} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[4].poster_url} alt={data.titles.items[4].title} w={44} h={66} fit="cover" radius="sm" />
          ) : <Text size="xs" w={44}>No poster</Text>}
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text fw={700}>5. {data.titles.items[4].title}</Text>
            <Text size="sm">{data.titles.items[4].library} · {data.titles.items[4].stage}</Text>
            <Text size="sm">Estimated Holding → Removal: {data.titles.items[4].estimated_removal_stage_at ?? "Unknown"}</Text>
            {data.titles.items[4].jellyfin_url ? <Anchor size="xs" href={data.titles.items[4].jellyfin_url} target="_blank">Open in Jellyfin</Anchor> : <Text size="xs">Jellyfin match unavailable</Text>}
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[5] ? (
        <Group wrap="nowrap" align="flex-start" gap="sm" style={{ border: "1px solid #666", borderRadius: "12px", padding: "8px" }}>
          {data.titles.items[5].poster_url ? (
            data.titles.items[5].jellyfin_url ? <Anchor href={data.titles.items[5].jellyfin_url} target="_blank" aria-label={data.titles.items[5].title}><Image src={data.titles.items[5].poster_url} alt={data.titles.items[5].title} w={44} h={66} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[5].poster_url} alt={data.titles.items[5].title} w={44} h={66} fit="cover" radius="sm" />
          ) : <Text size="xs" w={44}>No poster</Text>}
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text fw={700}>6. {data.titles.items[5].title}</Text>
            <Text size="sm">{data.titles.items[5].library} · {data.titles.items[5].stage}</Text>
            <Text size="sm">Estimated Holding → Removal: {data.titles.items[5].estimated_removal_stage_at ?? "Unknown"}</Text>
            {data.titles.items[5].jellyfin_url ? <Anchor size="xs" href={data.titles.items[5].jellyfin_url} target="_blank">Open in Jellyfin</Anchor> : <Text size="xs">Jellyfin match unavailable</Text>}
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[6] ? (
        <Group wrap="nowrap" align="flex-start" gap="sm" style={{ border: "1px solid #666", borderRadius: "12px", padding: "8px" }}>
          {data.titles.items[6].poster_url ? (
            data.titles.items[6].jellyfin_url ? <Anchor href={data.titles.items[6].jellyfin_url} target="_blank" aria-label={data.titles.items[6].title}><Image src={data.titles.items[6].poster_url} alt={data.titles.items[6].title} w={44} h={66} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[6].poster_url} alt={data.titles.items[6].title} w={44} h={66} fit="cover" radius="sm" />
          ) : <Text size="xs" w={44}>No poster</Text>}
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text fw={700}>7. {data.titles.items[6].title}</Text>
            <Text size="sm">{data.titles.items[6].library} · {data.titles.items[6].stage}</Text>
            <Text size="sm">Estimated Holding → Removal: {data.titles.items[6].estimated_removal_stage_at ?? "Unknown"}</Text>
            {data.titles.items[6].jellyfin_url ? <Anchor size="xs" href={data.titles.items[6].jellyfin_url} target="_blank">Open in Jellyfin</Anchor> : <Text size="xs">Jellyfin match unavailable</Text>}
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[7] ? (
        <Group wrap="nowrap" align="flex-start" gap="sm" style={{ border: "1px solid #666", borderRadius: "12px", padding: "8px" }}>
          {data.titles.items[7].poster_url ? (
            data.titles.items[7].jellyfin_url ? <Anchor href={data.titles.items[7].jellyfin_url} target="_blank" aria-label={data.titles.items[7].title}><Image src={data.titles.items[7].poster_url} alt={data.titles.items[7].title} w={44} h={66} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[7].poster_url} alt={data.titles.items[7].title} w={44} h={66} fit="cover" radius="sm" />
          ) : <Text size="xs" w={44}>No poster</Text>}
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text fw={700}>8. {data.titles.items[7].title}</Text>
            <Text size="sm">{data.titles.items[7].library} · {data.titles.items[7].stage}</Text>
            <Text size="sm">Estimated Holding → Removal: {data.titles.items[7].estimated_removal_stage_at ?? "Unknown"}</Text>
            {data.titles.items[7].jellyfin_url ? <Anchor size="xs" href={data.titles.items[7].jellyfin_url} target="_blank">Open in Jellyfin</Anchor> : <Text size="xs">Jellyfin match unavailable</Text>}
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[8] ? (
        <Group wrap="nowrap" align="flex-start" gap="sm" style={{ border: "1px solid #666", borderRadius: "12px", padding: "8px" }}>
          {data.titles.items[8].poster_url ? (
            data.titles.items[8].jellyfin_url ? <Anchor href={data.titles.items[8].jellyfin_url} target="_blank" aria-label={data.titles.items[8].title}><Image src={data.titles.items[8].poster_url} alt={data.titles.items[8].title} w={44} h={66} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[8].poster_url} alt={data.titles.items[8].title} w={44} h={66} fit="cover" radius="sm" />
          ) : <Text size="xs" w={44}>No poster</Text>}
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text fw={700}>9. {data.titles.items[8].title}</Text>
            <Text size="sm">{data.titles.items[8].library} · {data.titles.items[8].stage}</Text>
            <Text size="sm">Estimated Holding → Removal: {data.titles.items[8].estimated_removal_stage_at ?? "Unknown"}</Text>
            {data.titles.items[8].jellyfin_url ? <Anchor size="xs" href={data.titles.items[8].jellyfin_url} target="_blank">Open in Jellyfin</Anchor> : <Text size="xs">Jellyfin match unavailable</Text>}
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[9] ? (
        <Group wrap="nowrap" align="flex-start" gap="sm" style={{ border: "1px solid #666", borderRadius: "12px", padding: "8px" }}>
          {data.titles.items[9].poster_url ? (
            data.titles.items[9].jellyfin_url ? <Anchor href={data.titles.items[9].jellyfin_url} target="_blank" aria-label={data.titles.items[9].title}><Image src={data.titles.items[9].poster_url} alt={data.titles.items[9].title} w={44} h={66} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[9].poster_url} alt={data.titles.items[9].title} w={44} h={66} fit="cover" radius="sm" />
          ) : <Text size="xs" w={44}>No poster</Text>}
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text fw={700}>10. {data.titles.items[9].title}</Text>
            <Text size="sm">{data.titles.items[9].library} · {data.titles.items[9].stage}</Text>
            <Text size="sm">Estimated Holding → Removal: {data.titles.items[9].estimated_removal_stage_at ?? "Unknown"}</Text>
            {data.titles.items[9].jellyfin_url ? <Anchor size="xs" href={data.titles.items[9].jellyfin_url} target="_blank">Open in Jellyfin</Anchor> : <Text size="xs">Jellyfin match unavailable</Text>}
          </Stack>
        </Group>
      ) : null}
      {data.titles.truncated ? <Text size="sm">Showing 10 of {data.titles.total_records} tracking records.</Text> : null}
    </Stack>
  )}
</Stack>
