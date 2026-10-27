<Stack gap={6}>
  <Text fw={700}>TV leaving soon</Text>
  {status.titles?.loading ? (
    <Text size="sm" role="status">Refreshing titles...</Text>
  ) : !status.titles?.ok || data.titles?.schema_version !== 1 || data.titles?.status !== "advisory_only" || data.titles?.view !== "leaving-soon" || data.titles?.library_filter !== "TV" || !data.titles?.items ? (
    <Text size="sm" role="status">Title list unavailable</Text>
  ) : data.titles.items.length === 0 ? (
    <Text size="sm">No TV tracking records in Holding</Text>
  ) : (
    <Stack gap={6}>
      {data.titles.items[0] ? (
        <Group wrap="nowrap" align="center" gap={8} style={{ border: "1px solid #334155", borderLeft: "3px solid #fbbf24", borderRadius: "10px", padding: "6px 8px", background: "linear-gradient(110deg, #182334, #111827)" }}>
          {data.titles.items[0].poster_url ? (
            data.titles.items[0].jellyfin_url ? <Anchor href={data.titles.items[0].jellyfin_url} target="_blank" aria-label={data.titles.items[0].title} style={{ flexShrink: 0 }}><Image src={data.titles.items[0].poster_url} alt={data.titles.items[0].title} w={36} h={54} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[0].poster_url} alt={data.titles.items[0].title} w={36} h={54} fit="cover" radius="sm" />
          ) : <Text w={36} h={54} style={{ display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "#253247", borderRadius: "4px", fontSize: "10px", flexShrink: 0 }}>{data.titles.items[0].library === "TV" ? "TV" : "FILM"}</Text>}
          <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
            <Text size="sm" fw={600} title={data.titles.items[0].title} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#f1f5f9" }}>1. {data.titles.items[0].title}</Text>
            <Group wrap="nowrap" gap={6}>
              <Text style={{ fontSize: "10px", fontWeight: 700, letterSpacing: "0.06em", color: "#fbbf24", backgroundColor: "rgba(245,158,11,0.14)", padding: "1px 6px", borderRadius: "999px" }}>HOLDING</Text>
              <Text size="xs" style={{ color: "#94a3b8" }}>{data.titles.items[0].library === "TV" ? "TV show" : "Movie"}</Text>
            </Group>
            <Text size="xs" title="Saved date as recorded; no timezone conversion" style={{ color: "#cbd5e1" }}>Est. removal stage: {data.titles.items[0].estimated_removal_stage_at?.length >= 16 ? data.titles.items[0].estimated_removal_stage_at[5] + data.titles.items[0].estimated_removal_stage_at[6] + "/" + data.titles.items[0].estimated_removal_stage_at[8] + data.titles.items[0].estimated_removal_stage_at[9] + "/" + data.titles.items[0].estimated_removal_stage_at[0] + data.titles.items[0].estimated_removal_stage_at[1] + data.titles.items[0].estimated_removal_stage_at[2] + data.titles.items[0].estimated_removal_stage_at[3] + " " + data.titles.items[0].estimated_removal_stage_at[11] + data.titles.items[0].estimated_removal_stage_at[12] + ":" + data.titles.items[0].estimated_removal_stage_at[14] + data.titles.items[0].estimated_removal_stage_at[15] : "Date unavailable"}</Text>
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[1] ? (
        <Group wrap="nowrap" align="center" gap={8} style={{ border: "1px solid #334155", borderLeft: "3px solid #fbbf24", borderRadius: "10px", padding: "6px 8px", background: "linear-gradient(110deg, #182334, #111827)" }}>
          {data.titles.items[1].poster_url ? (
            data.titles.items[1].jellyfin_url ? <Anchor href={data.titles.items[1].jellyfin_url} target="_blank" aria-label={data.titles.items[1].title} style={{ flexShrink: 0 }}><Image src={data.titles.items[1].poster_url} alt={data.titles.items[1].title} w={36} h={54} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[1].poster_url} alt={data.titles.items[1].title} w={36} h={54} fit="cover" radius="sm" />
          ) : <Text w={36} h={54} style={{ display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "#253247", borderRadius: "4px", fontSize: "10px", flexShrink: 0 }}>{data.titles.items[1].library === "TV" ? "TV" : "FILM"}</Text>}
          <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
            <Text size="sm" fw={600} title={data.titles.items[1].title} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#f1f5f9" }}>2. {data.titles.items[1].title}</Text>
            <Group wrap="nowrap" gap={6}>
              <Text style={{ fontSize: "10px", fontWeight: 700, letterSpacing: "0.06em", color: "#fbbf24", backgroundColor: "rgba(245,158,11,0.14)", padding: "1px 6px", borderRadius: "999px" }}>HOLDING</Text>
              <Text size="xs" style={{ color: "#94a3b8" }}>{data.titles.items[1].library === "TV" ? "TV show" : "Movie"}</Text>
            </Group>
            <Text size="xs" title="Saved date as recorded; no timezone conversion" style={{ color: "#cbd5e1" }}>Est. removal stage: {data.titles.items[1].estimated_removal_stage_at?.length >= 16 ? data.titles.items[1].estimated_removal_stage_at[5] + data.titles.items[1].estimated_removal_stage_at[6] + "/" + data.titles.items[1].estimated_removal_stage_at[8] + data.titles.items[1].estimated_removal_stage_at[9] + "/" + data.titles.items[1].estimated_removal_stage_at[0] + data.titles.items[1].estimated_removal_stage_at[1] + data.titles.items[1].estimated_removal_stage_at[2] + data.titles.items[1].estimated_removal_stage_at[3] + " " + data.titles.items[1].estimated_removal_stage_at[11] + data.titles.items[1].estimated_removal_stage_at[12] + ":" + data.titles.items[1].estimated_removal_stage_at[14] + data.titles.items[1].estimated_removal_stage_at[15] : "Date unavailable"}</Text>
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[2] ? (
        <Group wrap="nowrap" align="center" gap={8} style={{ border: "1px solid #334155", borderLeft: "3px solid #fbbf24", borderRadius: "10px", padding: "6px 8px", background: "linear-gradient(110deg, #182334, #111827)" }}>
          {data.titles.items[2].poster_url ? (
            data.titles.items[2].jellyfin_url ? <Anchor href={data.titles.items[2].jellyfin_url} target="_blank" aria-label={data.titles.items[2].title} style={{ flexShrink: 0 }}><Image src={data.titles.items[2].poster_url} alt={data.titles.items[2].title} w={36} h={54} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[2].poster_url} alt={data.titles.items[2].title} w={36} h={54} fit="cover" radius="sm" />
          ) : <Text w={36} h={54} style={{ display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "#253247", borderRadius: "4px", fontSize: "10px", flexShrink: 0 }}>{data.titles.items[2].library === "TV" ? "TV" : "FILM"}</Text>}
          <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
            <Text size="sm" fw={600} title={data.titles.items[2].title} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#f1f5f9" }}>3. {data.titles.items[2].title}</Text>
            <Group wrap="nowrap" gap={6}>
              <Text style={{ fontSize: "10px", fontWeight: 700, letterSpacing: "0.06em", color: "#fbbf24", backgroundColor: "rgba(245,158,11,0.14)", padding: "1px 6px", borderRadius: "999px" }}>HOLDING</Text>
              <Text size="xs" style={{ color: "#94a3b8" }}>{data.titles.items[2].library === "TV" ? "TV show" : "Movie"}</Text>
            </Group>
            <Text size="xs" title="Saved date as recorded; no timezone conversion" style={{ color: "#cbd5e1" }}>Est. removal stage: {data.titles.items[2].estimated_removal_stage_at?.length >= 16 ? data.titles.items[2].estimated_removal_stage_at[5] + data.titles.items[2].estimated_removal_stage_at[6] + "/" + data.titles.items[2].estimated_removal_stage_at[8] + data.titles.items[2].estimated_removal_stage_at[9] + "/" + data.titles.items[2].estimated_removal_stage_at[0] + data.titles.items[2].estimated_removal_stage_at[1] + data.titles.items[2].estimated_removal_stage_at[2] + data.titles.items[2].estimated_removal_stage_at[3] + " " + data.titles.items[2].estimated_removal_stage_at[11] + data.titles.items[2].estimated_removal_stage_at[12] + ":" + data.titles.items[2].estimated_removal_stage_at[14] + data.titles.items[2].estimated_removal_stage_at[15] : "Date unavailable"}</Text>
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[3] ? (
        <Group wrap="nowrap" align="center" gap={8} style={{ border: "1px solid #334155", borderLeft: "3px solid #fbbf24", borderRadius: "10px", padding: "6px 8px", background: "linear-gradient(110deg, #182334, #111827)" }}>
          {data.titles.items[3].poster_url ? (
            data.titles.items[3].jellyfin_url ? <Anchor href={data.titles.items[3].jellyfin_url} target="_blank" aria-label={data.titles.items[3].title} style={{ flexShrink: 0 }}><Image src={data.titles.items[3].poster_url} alt={data.titles.items[3].title} w={36} h={54} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[3].poster_url} alt={data.titles.items[3].title} w={36} h={54} fit="cover" radius="sm" />
          ) : <Text w={36} h={54} style={{ display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "#253247", borderRadius: "4px", fontSize: "10px", flexShrink: 0 }}>{data.titles.items[3].library === "TV" ? "TV" : "FILM"}</Text>}
          <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
            <Text size="sm" fw={600} title={data.titles.items[3].title} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#f1f5f9" }}>4. {data.titles.items[3].title}</Text>
            <Group wrap="nowrap" gap={6}>
              <Text style={{ fontSize: "10px", fontWeight: 700, letterSpacing: "0.06em", color: "#fbbf24", backgroundColor: "rgba(245,158,11,0.14)", padding: "1px 6px", borderRadius: "999px" }}>HOLDING</Text>
              <Text size="xs" style={{ color: "#94a3b8" }}>{data.titles.items[3].library === "TV" ? "TV show" : "Movie"}</Text>
            </Group>
            <Text size="xs" title="Saved date as recorded; no timezone conversion" style={{ color: "#cbd5e1" }}>Est. removal stage: {data.titles.items[3].estimated_removal_stage_at?.length >= 16 ? data.titles.items[3].estimated_removal_stage_at[5] + data.titles.items[3].estimated_removal_stage_at[6] + "/" + data.titles.items[3].estimated_removal_stage_at[8] + data.titles.items[3].estimated_removal_stage_at[9] + "/" + data.titles.items[3].estimated_removal_stage_at[0] + data.titles.items[3].estimated_removal_stage_at[1] + data.titles.items[3].estimated_removal_stage_at[2] + data.titles.items[3].estimated_removal_stage_at[3] + " " + data.titles.items[3].estimated_removal_stage_at[11] + data.titles.items[3].estimated_removal_stage_at[12] + ":" + data.titles.items[3].estimated_removal_stage_at[14] + data.titles.items[3].estimated_removal_stage_at[15] : "Date unavailable"}</Text>
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[4] ? (
        <Group wrap="nowrap" align="center" gap={8} style={{ border: "1px solid #334155", borderLeft: "3px solid #fbbf24", borderRadius: "10px", padding: "6px 8px", background: "linear-gradient(110deg, #182334, #111827)" }}>
          {data.titles.items[4].poster_url ? (
            data.titles.items[4].jellyfin_url ? <Anchor href={data.titles.items[4].jellyfin_url} target="_blank" aria-label={data.titles.items[4].title} style={{ flexShrink: 0 }}><Image src={data.titles.items[4].poster_url} alt={data.titles.items[4].title} w={36} h={54} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[4].poster_url} alt={data.titles.items[4].title} w={36} h={54} fit="cover" radius="sm" />
          ) : <Text w={36} h={54} style={{ display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "#253247", borderRadius: "4px", fontSize: "10px", flexShrink: 0 }}>{data.titles.items[4].library === "TV" ? "TV" : "FILM"}</Text>}
          <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
            <Text size="sm" fw={600} title={data.titles.items[4].title} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#f1f5f9" }}>5. {data.titles.items[4].title}</Text>
            <Group wrap="nowrap" gap={6}>
              <Text style={{ fontSize: "10px", fontWeight: 700, letterSpacing: "0.06em", color: "#fbbf24", backgroundColor: "rgba(245,158,11,0.14)", padding: "1px 6px", borderRadius: "999px" }}>HOLDING</Text>
              <Text size="xs" style={{ color: "#94a3b8" }}>{data.titles.items[4].library === "TV" ? "TV show" : "Movie"}</Text>
            </Group>
            <Text size="xs" title="Saved date as recorded; no timezone conversion" style={{ color: "#cbd5e1" }}>Est. removal stage: {data.titles.items[4].estimated_removal_stage_at?.length >= 16 ? data.titles.items[4].estimated_removal_stage_at[5] + data.titles.items[4].estimated_removal_stage_at[6] + "/" + data.titles.items[4].estimated_removal_stage_at[8] + data.titles.items[4].estimated_removal_stage_at[9] + "/" + data.titles.items[4].estimated_removal_stage_at[0] + data.titles.items[4].estimated_removal_stage_at[1] + data.titles.items[4].estimated_removal_stage_at[2] + data.titles.items[4].estimated_removal_stage_at[3] + " " + data.titles.items[4].estimated_removal_stage_at[11] + data.titles.items[4].estimated_removal_stage_at[12] + ":" + data.titles.items[4].estimated_removal_stage_at[14] + data.titles.items[4].estimated_removal_stage_at[15] : "Date unavailable"}</Text>
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[5] ? (
        <Group wrap="nowrap" align="center" gap={8} style={{ border: "1px solid #334155", borderLeft: "3px solid #fbbf24", borderRadius: "10px", padding: "6px 8px", background: "linear-gradient(110deg, #182334, #111827)" }}>
          {data.titles.items[5].poster_url ? (
            data.titles.items[5].jellyfin_url ? <Anchor href={data.titles.items[5].jellyfin_url} target="_blank" aria-label={data.titles.items[5].title} style={{ flexShrink: 0 }}><Image src={data.titles.items[5].poster_url} alt={data.titles.items[5].title} w={36} h={54} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[5].poster_url} alt={data.titles.items[5].title} w={36} h={54} fit="cover" radius="sm" />
          ) : <Text w={36} h={54} style={{ display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "#253247", borderRadius: "4px", fontSize: "10px", flexShrink: 0 }}>{data.titles.items[5].library === "TV" ? "TV" : "FILM"}</Text>}
          <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
            <Text size="sm" fw={600} title={data.titles.items[5].title} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#f1f5f9" }}>6. {data.titles.items[5].title}</Text>
            <Group wrap="nowrap" gap={6}>
              <Text style={{ fontSize: "10px", fontWeight: 700, letterSpacing: "0.06em", color: "#fbbf24", backgroundColor: "rgba(245,158,11,0.14)", padding: "1px 6px", borderRadius: "999px" }}>HOLDING</Text>
              <Text size="xs" style={{ color: "#94a3b8" }}>{data.titles.items[5].library === "TV" ? "TV show" : "Movie"}</Text>
            </Group>
            <Text size="xs" title="Saved date as recorded; no timezone conversion" style={{ color: "#cbd5e1" }}>Est. removal stage: {data.titles.items[5].estimated_removal_stage_at?.length >= 16 ? data.titles.items[5].estimated_removal_stage_at[5] + data.titles.items[5].estimated_removal_stage_at[6] + "/" + data.titles.items[5].estimated_removal_stage_at[8] + data.titles.items[5].estimated_removal_stage_at[9] + "/" + data.titles.items[5].estimated_removal_stage_at[0] + data.titles.items[5].estimated_removal_stage_at[1] + data.titles.items[5].estimated_removal_stage_at[2] + data.titles.items[5].estimated_removal_stage_at[3] + " " + data.titles.items[5].estimated_removal_stage_at[11] + data.titles.items[5].estimated_removal_stage_at[12] + ":" + data.titles.items[5].estimated_removal_stage_at[14] + data.titles.items[5].estimated_removal_stage_at[15] : "Date unavailable"}</Text>
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[6] ? (
        <Group wrap="nowrap" align="center" gap={8} style={{ border: "1px solid #334155", borderLeft: "3px solid #fbbf24", borderRadius: "10px", padding: "6px 8px", background: "linear-gradient(110deg, #182334, #111827)" }}>
          {data.titles.items[6].poster_url ? (
            data.titles.items[6].jellyfin_url ? <Anchor href={data.titles.items[6].jellyfin_url} target="_blank" aria-label={data.titles.items[6].title} style={{ flexShrink: 0 }}><Image src={data.titles.items[6].poster_url} alt={data.titles.items[6].title} w={36} h={54} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[6].poster_url} alt={data.titles.items[6].title} w={36} h={54} fit="cover" radius="sm" />
          ) : <Text w={36} h={54} style={{ display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "#253247", borderRadius: "4px", fontSize: "10px", flexShrink: 0 }}>{data.titles.items[6].library === "TV" ? "TV" : "FILM"}</Text>}
          <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
            <Text size="sm" fw={600} title={data.titles.items[6].title} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#f1f5f9" }}>7. {data.titles.items[6].title}</Text>
            <Group wrap="nowrap" gap={6}>
              <Text style={{ fontSize: "10px", fontWeight: 700, letterSpacing: "0.06em", color: "#fbbf24", backgroundColor: "rgba(245,158,11,0.14)", padding: "1px 6px", borderRadius: "999px" }}>HOLDING</Text>
              <Text size="xs" style={{ color: "#94a3b8" }}>{data.titles.items[6].library === "TV" ? "TV show" : "Movie"}</Text>
            </Group>
            <Text size="xs" title="Saved date as recorded; no timezone conversion" style={{ color: "#cbd5e1" }}>Est. removal stage: {data.titles.items[6].estimated_removal_stage_at?.length >= 16 ? data.titles.items[6].estimated_removal_stage_at[5] + data.titles.items[6].estimated_removal_stage_at[6] + "/" + data.titles.items[6].estimated_removal_stage_at[8] + data.titles.items[6].estimated_removal_stage_at[9] + "/" + data.titles.items[6].estimated_removal_stage_at[0] + data.titles.items[6].estimated_removal_stage_at[1] + data.titles.items[6].estimated_removal_stage_at[2] + data.titles.items[6].estimated_removal_stage_at[3] + " " + data.titles.items[6].estimated_removal_stage_at[11] + data.titles.items[6].estimated_removal_stage_at[12] + ":" + data.titles.items[6].estimated_removal_stage_at[14] + data.titles.items[6].estimated_removal_stage_at[15] : "Date unavailable"}</Text>
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[7] ? (
        <Group wrap="nowrap" align="center" gap={8} style={{ border: "1px solid #334155", borderLeft: "3px solid #fbbf24", borderRadius: "10px", padding: "6px 8px", background: "linear-gradient(110deg, #182334, #111827)" }}>
          {data.titles.items[7].poster_url ? (
            data.titles.items[7].jellyfin_url ? <Anchor href={data.titles.items[7].jellyfin_url} target="_blank" aria-label={data.titles.items[7].title} style={{ flexShrink: 0 }}><Image src={data.titles.items[7].poster_url} alt={data.titles.items[7].title} w={36} h={54} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[7].poster_url} alt={data.titles.items[7].title} w={36} h={54} fit="cover" radius="sm" />
          ) : <Text w={36} h={54} style={{ display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "#253247", borderRadius: "4px", fontSize: "10px", flexShrink: 0 }}>{data.titles.items[7].library === "TV" ? "TV" : "FILM"}</Text>}
          <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
            <Text size="sm" fw={600} title={data.titles.items[7].title} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#f1f5f9" }}>8. {data.titles.items[7].title}</Text>
            <Group wrap="nowrap" gap={6}>
              <Text style={{ fontSize: "10px", fontWeight: 700, letterSpacing: "0.06em", color: "#fbbf24", backgroundColor: "rgba(245,158,11,0.14)", padding: "1px 6px", borderRadius: "999px" }}>HOLDING</Text>
              <Text size="xs" style={{ color: "#94a3b8" }}>{data.titles.items[7].library === "TV" ? "TV show" : "Movie"}</Text>
            </Group>
            <Text size="xs" title="Saved date as recorded; no timezone conversion" style={{ color: "#cbd5e1" }}>Est. removal stage: {data.titles.items[7].estimated_removal_stage_at?.length >= 16 ? data.titles.items[7].estimated_removal_stage_at[5] + data.titles.items[7].estimated_removal_stage_at[6] + "/" + data.titles.items[7].estimated_removal_stage_at[8] + data.titles.items[7].estimated_removal_stage_at[9] + "/" + data.titles.items[7].estimated_removal_stage_at[0] + data.titles.items[7].estimated_removal_stage_at[1] + data.titles.items[7].estimated_removal_stage_at[2] + data.titles.items[7].estimated_removal_stage_at[3] + " " + data.titles.items[7].estimated_removal_stage_at[11] + data.titles.items[7].estimated_removal_stage_at[12] + ":" + data.titles.items[7].estimated_removal_stage_at[14] + data.titles.items[7].estimated_removal_stage_at[15] : "Date unavailable"}</Text>
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[8] ? (
        <Group wrap="nowrap" align="center" gap={8} style={{ border: "1px solid #334155", borderLeft: "3px solid #fbbf24", borderRadius: "10px", padding: "6px 8px", background: "linear-gradient(110deg, #182334, #111827)" }}>
          {data.titles.items[8].poster_url ? (
            data.titles.items[8].jellyfin_url ? <Anchor href={data.titles.items[8].jellyfin_url} target="_blank" aria-label={data.titles.items[8].title} style={{ flexShrink: 0 }}><Image src={data.titles.items[8].poster_url} alt={data.titles.items[8].title} w={36} h={54} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[8].poster_url} alt={data.titles.items[8].title} w={36} h={54} fit="cover" radius="sm" />
          ) : <Text w={36} h={54} style={{ display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "#253247", borderRadius: "4px", fontSize: "10px", flexShrink: 0 }}>{data.titles.items[8].library === "TV" ? "TV" : "FILM"}</Text>}
          <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
            <Text size="sm" fw={600} title={data.titles.items[8].title} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#f1f5f9" }}>9. {data.titles.items[8].title}</Text>
            <Group wrap="nowrap" gap={6}>
              <Text style={{ fontSize: "10px", fontWeight: 700, letterSpacing: "0.06em", color: "#fbbf24", backgroundColor: "rgba(245,158,11,0.14)", padding: "1px 6px", borderRadius: "999px" }}>HOLDING</Text>
              <Text size="xs" style={{ color: "#94a3b8" }}>{data.titles.items[8].library === "TV" ? "TV show" : "Movie"}</Text>
            </Group>
            <Text size="xs" title="Saved date as recorded; no timezone conversion" style={{ color: "#cbd5e1" }}>Est. removal stage: {data.titles.items[8].estimated_removal_stage_at?.length >= 16 ? data.titles.items[8].estimated_removal_stage_at[5] + data.titles.items[8].estimated_removal_stage_at[6] + "/" + data.titles.items[8].estimated_removal_stage_at[8] + data.titles.items[8].estimated_removal_stage_at[9] + "/" + data.titles.items[8].estimated_removal_stage_at[0] + data.titles.items[8].estimated_removal_stage_at[1] + data.titles.items[8].estimated_removal_stage_at[2] + data.titles.items[8].estimated_removal_stage_at[3] + " " + data.titles.items[8].estimated_removal_stage_at[11] + data.titles.items[8].estimated_removal_stage_at[12] + ":" + data.titles.items[8].estimated_removal_stage_at[14] + data.titles.items[8].estimated_removal_stage_at[15] : "Date unavailable"}</Text>
          </Stack>
        </Group>
      ) : null}
      {data.titles.items[9] ? (
        <Group wrap="nowrap" align="center" gap={8} style={{ border: "1px solid #334155", borderLeft: "3px solid #fbbf24", borderRadius: "10px", padding: "6px 8px", background: "linear-gradient(110deg, #182334, #111827)" }}>
          {data.titles.items[9].poster_url ? (
            data.titles.items[9].jellyfin_url ? <Anchor href={data.titles.items[9].jellyfin_url} target="_blank" aria-label={data.titles.items[9].title} style={{ flexShrink: 0 }}><Image src={data.titles.items[9].poster_url} alt={data.titles.items[9].title} w={36} h={54} fit="cover" radius="sm" /></Anchor> : <Image src={data.titles.items[9].poster_url} alt={data.titles.items[9].title} w={36} h={54} fit="cover" radius="sm" />
          ) : <Text w={36} h={54} style={{ display: "flex", alignItems: "center", justifyContent: "center", backgroundColor: "#253247", borderRadius: "4px", fontSize: "10px", flexShrink: 0 }}>{data.titles.items[9].library === "TV" ? "TV" : "FILM"}</Text>}
          <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
            <Text size="sm" fw={600} title={data.titles.items[9].title} style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: "#f1f5f9" }}>10. {data.titles.items[9].title}</Text>
            <Group wrap="nowrap" gap={6}>
              <Text style={{ fontSize: "10px", fontWeight: 700, letterSpacing: "0.06em", color: "#fbbf24", backgroundColor: "rgba(245,158,11,0.14)", padding: "1px 6px", borderRadius: "999px" }}>HOLDING</Text>
              <Text size="xs" style={{ color: "#94a3b8" }}>{data.titles.items[9].library === "TV" ? "TV show" : "Movie"}</Text>
            </Group>
            <Text size="xs" title="Saved date as recorded; no timezone conversion" style={{ color: "#cbd5e1" }}>Est. removal stage: {data.titles.items[9].estimated_removal_stage_at?.length >= 16 ? data.titles.items[9].estimated_removal_stage_at[5] + data.titles.items[9].estimated_removal_stage_at[6] + "/" + data.titles.items[9].estimated_removal_stage_at[8] + data.titles.items[9].estimated_removal_stage_at[9] + "/" + data.titles.items[9].estimated_removal_stage_at[0] + data.titles.items[9].estimated_removal_stage_at[1] + data.titles.items[9].estimated_removal_stage_at[2] + data.titles.items[9].estimated_removal_stage_at[3] + " " + data.titles.items[9].estimated_removal_stage_at[11] + data.titles.items[9].estimated_removal_stage_at[12] + ":" + data.titles.items[9].estimated_removal_stage_at[14] + data.titles.items[9].estimated_removal_stage_at[15] : "Date unavailable"}</Text>
          </Stack>
        </Group>
      ) : null}
      {data.titles.truncated ? <Text size="xs">Showing 10 of {data.titles.total_records} tracking records.</Text> : null}
    </Stack>
  )}
</Stack>
