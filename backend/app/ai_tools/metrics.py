from collections import Counter, defaultdict
from threading import Lock


class ToolMetrics:
    def __init__(self):
        self._lock = Lock(); self.counts = Counter(); self.durations = defaultdict(list)

    def record(self, tool: str, status: str, duration_ms: int, *, cache_hit=False, truncated=False):
        with self._lock:
            self.counts[(tool, status)] += 1
            if cache_hit: self.counts[(tool, "cache_hit")] += 1
            if truncated: self.counts[(tool, "truncated")] += 1
            samples = self.durations[tool]; samples.append(duration_ms)
            if len(samples) > 1000: del samples[:-1000]

    def snapshot(self) -> dict:
        with self._lock:
            tools={tool for tool,_ in self.counts}
            output={}
            for tool in sorted(tools):
                statuses={status:count for (name,status),count in self.counts.items() if name==tool}
                samples=sorted(self.durations.get(tool,[])); total=sum(count for status,count in statuses.items() if status not in {"cache_hit","truncated"})
                successes=statuses.get("success",0)+statuses.get("partial",0)
                p95=samples[min(len(samples)-1,max(0,int(len(samples)*.95)-1))] if samples else None
                output[tool]={"calls":total,"success_rate":(successes/total if total else None),"error_rate":((total-successes)/total if total else None),
                    "timeouts":statuses.get("timeout",0),"cache_hits":statuses.get("cache_hit",0),"truncated":statuses.get("truncated",0),
                    "average_duration_ms":(sum(samples)/len(samples) if samples else None),"p95_duration_ms":p95,"status_counts":statuses}
            return output


tool_metrics = ToolMetrics()
