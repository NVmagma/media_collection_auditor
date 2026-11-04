"""Read previous schedule field names without rewriting saved configuration."""
SCHEDULE_ALIASES={'SQLITE_DAILY_RUN_TIME':'DAILY_RUN_TIME',
                  'SQLITE_DAILY_RUN_TIMEZONE':'DAILY_RUN_TIMEZONE'}


def normalize_schedule(values):
    result=dict(values)
    for previous,current in SCHEDULE_ALIASES.items():
        if current not in result and previous in result: result[current]=result[previous]
        result.pop(previous,None)
    return result
