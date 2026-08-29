import type { BenchmarkReport } from "../../../shared/types/benchmarks";
import { providerLabel } from "../../../domains/pipeline/model/pipelineSelection";
import { parserRoutingEvidence } from "../../../domains/pipeline/model/parserRouting";

export interface BenchmarkParserRouteMetric {
  provider: string;
  cases: number;
  failedCases: number;
  fallbackCases: number;
  correctFields: number;
  evaluatedFields: number;
  accuracy: number;
}

export interface BenchmarkParserRouteSummary {
  attributedCases: number;
  routes: BenchmarkParserRouteMetric[];
}

export function benchmarkParserRouteSummary(
  report: BenchmarkReport | null,
): BenchmarkParserRouteSummary {
  if (!report || report.parser_provider !== "auto") {
    return { attributedCases: 0, routes: [] };
  }

  const routes = new Map<
    string,
    Omit<BenchmarkParserRouteMetric, "accuracy">
  >();
  let attributedCases = 0;
  for (const benchmarkCase of report.cases) {
    const routing = parserRoutingEvidence(benchmarkCase.parser_routing);
    if (
      !routing ||
      routing.provider !== report.parser_provider ||
      routing.layoutProfile !== report.layout_profile
    ) {
      continue;
    }
    attributedCases += 1;
    const current = routes.get(routing.selectedProvider) ?? {
      provider: routing.selectedProvider,
      cases: 0,
      failedCases: 0,
      fallbackCases: 0,
      correctFields: 0,
      evaluatedFields: 0,
    };
    current.cases += 1;
    current.failedCases += benchmarkCase.status === "error" ? 1 : 0;
    current.fallbackCases += routing.fallbackFrom ? 1 : 0;
    current.correctFields += benchmarkCase.correct_fields;
    current.evaluatedFields += benchmarkCase.evaluated_fields;
    routes.set(routing.selectedProvider, current);
  }

  return {
    attributedCases,
    routes: [...routes.values()]
      .map((route) => ({
        ...route,
        accuracy:
          route.evaluatedFields > 0
            ? route.correctFields / route.evaluatedFields
            : 0,
      }))
      .sort((left, right) =>
        providerLabel(left.provider).localeCompare(
          providerLabel(right.provider),
        ),
      ),
  };
}
