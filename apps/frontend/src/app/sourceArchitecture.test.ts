/// <reference types="node" />

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import { parse as parseCss } from "postcss";
import parseCssValue from "postcss-value-parser";
import { globSync } from "tinyglobby";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const SOURCE_ROOT = resolve(process.cwd(), "src");
const ALLOWED_LAYER_IMPORTS: Readonly<Record<string, ReadonlySet<string>>> = {
  bootstrap: new Set(["app"]),
  app: new Set(["app", "pages", "shared"]),
  pages: new Set(["pages", "workflows", "features", "shared"]),
  workflows: new Set(["workflows", "features", "domains", "shared"]),
  features: new Set(["features", "domains", "shared"]),
  domains: new Set(["domains", "shared"]),
  shared: new Set(["shared"]),
};
const ALLOWED_FEATURE_AREAS = new Set([
  "api",
  "components",
  "hooks",
  "lib",
  "model",
  "services",
  "store",
]);
const NON_COMPONENT_FEATURE_AREAS = new Set([
  "api",
  "hooks",
  "lib",
  "model",
  "services",
  "store",
]);
const JAVASCRIPT_EXTENSIONS = new Set([".cjs", ".js", ".jsx", ".mjs"]);
const WAVE_NINE_MUTATION_OWNERS: Readonly<Record<string, ReadonlySet<string>>> =
  {
    approveState: new Set([
      "domains/jobs/api/jobsApi.ts",
      "features/hand-review/services/handWorkflowCommands.ts",
    ]),
    archiveJobs: new Set([
      "domains/history/api/historyApi.ts",
      "features/history/services/archiveJobsCommand.ts",
    ]),
    completeTrainingReview: new Set([
      "domains/training/api/trainingApi.ts",
      "features/training/services/trainingReviewCommands.ts",
    ]),
    deleteJob: new Set([
      "domains/jobs/api/jobsApi.ts",
      "features/screenshots/services/deleteScreenshotCommand.ts",
    ]),
    importBenchmarkDataset: new Set([
      "domains/benchmarks/api/benchmarksApi.ts",
      "features/benchmark/services/importBenchmarkDatasetCommand.ts",
    ]),
    recordTrainingDecision: new Set([
      "domains/training/api/trainingApi.ts",
      "features/training/services/trainingReviewCommands.ts",
    ]),
    reopenTrainingReview: new Set([
      "domains/training/api/trainingApi.ts",
      "features/training/services/trainingReviewCommands.ts",
    ]),
    requestRecommendation: new Set([
      "domains/recommendations/api/recommendationsApi.ts",
      "features/hand-review/services/handWorkflowCommands.ts",
    ]),
    restoreApplicationBackup: new Set([
      "domains/backups/api/backupsApi.ts",
      "features/backups/services/restoreApplicationBackupCommand.ts",
    ]),
    setBenchmarkInclusion: new Set([
      "domains/benchmarks/api/benchmarksApi.ts",
      "features/benchmark/services/setBenchmarkInclusionCommand.ts",
    ]),
    updateJobMetadata: new Set([
      "domains/jobs/api/jobsApi.ts",
      "features/screenshots/services/updateScreenshotMetadataCommand.ts",
    ]),
    uploadScreenshot: new Set([
      "domains/jobs/api/jobsApi.ts",
      "features/capture/services/uploadScreenshotCommand.ts",
    ]),
  };

function isWaveNineMutation(value: string): boolean {
  return Object.prototype.hasOwnProperty.call(WAVE_NINE_MUTATION_OWNERS, value);
}

const LEGACY_RAW_TRANSPORT_OWNERS = new Set([
  "shared/api/benchmarks.ts",
  "shared/api/mcp.ts",
  "shared/api/system.ts",
  "shared/api/transport.ts",
]);
const RAW_TRANSPORT_REFERENCES = new Set([
  "XMLHttpRequest",
  "fetch",
  "requestJson",
  "sendBeacon",
]);

function ownsRawTransport(sourcePath: string): boolean {
  const segments = sourcePath.split("/");
  return (
    (segments[0] === "domains" && segments[2] === "api") ||
    LEGACY_RAW_TRANSPORT_OWNERS.has(sourcePath)
  );
}

const SOURCE_EXTENSIONS = new Set([
  ".cjs",
  ".css",
  ".cts",
  ".js",
  ".jsx",
  ".mjs",
  ".mts",
  ".ts",
  ".tsx",
]);

function filesBelow(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? filesBelow(path) : [path];
  });
}

function sourceSegments(file: string): string[] {
  return relative(SOURCE_ROOT, file).split(sep);
}

function sourceLayer(sourcePath: readonly string[]): string | null {
  if (sourcePath.length === 1 && sourcePath[0] === "main.tsx") {
    return "bootstrap";
  }
  return Object.prototype.hasOwnProperty.call(
    ALLOWED_LAYER_IMPORTS,
    sourcePath[0],
  )
    ? sourcePath[0]
    : null;
}

function featureArea(sourcePath: readonly string[]): string | null {
  const area = sourcePath[2];
  return ["workflows", "features", "domains"].includes(sourcePath[0] ?? "") &&
    ALLOWED_FEATURE_AREAS.has(area)
    ? area
    : null;
}

function featurePlacementViolation(
  sourcePath: readonly string[],
): string | null {
  const area = featureArea(sourcePath);
  if (!area) {
    return "workflow, feature, or domain source must live in an allowed area";
  }

  const extension = extname(sourcePath[sourcePath.length - 1] ?? "");
  if ((extension === ".tsx" || extension === ".css") && area !== "components") {
    return `feature ${extension.slice(1).toUpperCase()} source must live in components`;
  }
  return null;
}

function isGeneratedOpenApiPath(sourcePath: readonly string[]): boolean {
  return (
    sourcePath[0] === "shared" &&
    sourcePath[1] === "api" &&
    sourcePath[2] === "generated"
  );
}

function domainCompatibilityFacadeImportAllowed(
  sourcePath: readonly string[],
  targetPath: readonly string[],
): boolean {
  const facade = sourcePath.join("/");
  const domain = targetPath.slice(0, 3).join("/");
  const module = (targetPath[3] ?? "").replace(/\.ts$/, "");
  return [
    ["shared/api/jobs.ts", "domains/jobs/api", "jobsApi"],
    ["shared/api/jobs.ts", "domains/recommendations/api", "recommendationsApi"],
    ["shared/api/history.ts", "domains/history/api", "historyApi"],
    ["shared/api/training.ts", "domains/training/api", "trainingApi"],
    ["shared/api/benchmarks.ts", "domains/benchmarks/api", "benchmarksApi"],
    ["shared/api/system.ts", "domains/backups/api", "backupsApi"],
  ].some(
    ([allowedFacade, allowedDomain, allowedModule]) =>
      facade === allowedFacade &&
      domain === allowedDomain &&
      module === allowedModule,
  );
}

function generatedOpenApiImportAllowed(sourcePath: readonly string[]): boolean {
  if (sourcePath[0] === "domains" && sourcePath[2] === "api") {
    return true;
  }
  if (sourcePath[0] !== "shared" || sourcePath[1] !== "api") {
    return false;
  }
  return ["client.ts", "core.ts", "transport.ts"].includes(
    sourcePath[sourcePath.length - 1] ?? "",
  );
}

const PEER_FEATURE_BASELINE_PATH = resolve(
  SOURCE_ROOT,
  "test/sourceArchitecturePeerFeatureBaseline.json",
);
const PEER_FEATURE_BASELINE_ENTRIES = JSON.parse(
  readFileSync(PEER_FEATURE_BASELINE_PATH, "utf8"),
) as string[];
const PEER_FEATURE_BASELINE = new Set(PEER_FEATURE_BASELINE_ENTRIES);

function isTestSupportPath(sourcePath: readonly string[]): boolean {
  return (
    sourcePath[0] === "test" ||
    sourcePath.includes("__tests__") ||
    sourcePath.some(
      (segment) => segment.includes(".test.") || segment.endsWith(".test"),
    )
  );
}

function sourceFiles(): string[] {
  return filesBelow(SOURCE_ROOT).filter((file) => {
    return (
      SOURCE_EXTENSIONS.has(extname(file)) &&
      !isTestSupportPath(sourceSegments(file))
    );
  });
}

function waveNineMutationBoundaryViolations(): string[] {
  const violations = new Set<string>();
  const scriptFiles = sourceFiles().filter((candidate) =>
    [".cjs", ".cts", ".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx"].includes(
      extname(candidate),
    ),
  );
  const program = ts.createProgram({
    rootNames: scriptFiles,
    options: {
      allowJs: true,
      checkJs: false,
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.ESNext,
      moduleResolution: ts.ModuleResolutionKind.Bundler,
      skipLibCheck: true,
      target: ts.ScriptTarget.ESNext,
    },
  });
  const checker = program.getTypeChecker();

  function resolvedAliasSymbol(
    initialSymbol: ts.Symbol | undefined,
  ): ts.Symbol | null {
    let symbol = initialSymbol;
    const seen = new Set<ts.Symbol>();
    while (symbol && (symbol.flags & ts.SymbolFlags.Alias) !== 0) {
      if (seen.has(symbol)) {
        break;
      }
      seen.add(symbol);
      const aliased = checker.getAliasedSymbol(symbol);
      if (aliased === symbol) {
        break;
      }
      symbol = aliased;
    }
    return symbol ?? null;
  }

  function resolvedSymbol(node: ts.Node): ts.Symbol | null {
    return resolvedAliasSymbol(checker.getSymbolAtLocation(node));
  }

  function declarationSourcePath(declaration: ts.Declaration): string | null {
    const declarationFile = resolve(declaration.getSourceFile().fileName);
    if (!declarationFile.startsWith(SOURCE_ROOT + sep)) {
      return null;
    }
    return sourceSegments(declarationFile).join("/");
  }

  function mutationNameForSymbol(symbol: ts.Symbol | null): string | null {
    const mutation = symbol?.getName() ?? "";
    if (!symbol || !isWaveNineMutation(mutation)) {
      return null;
    }
    const owners = WAVE_NINE_MUTATION_OWNERS[mutation];
    return symbol.declarations?.some((declaration) => {
      const declarationPath = declarationSourcePath(declaration);
      return declarationPath !== null && owners.has(declarationPath);
    })
      ? mutation
      : null;
  }

  function mutationSymbol(node: ts.Node): string | null {
    return mutationNameForSymbol(resolvedSymbol(node));
  }

  function rawTransportNameForSymbol(symbol: ts.Symbol | null): string | null {
    const transport = symbol?.getName() ?? "";
    if (!symbol || !RAW_TRANSPORT_REFERENCES.has(transport)) {
      return null;
    }
    const ownsDeclaration = symbol.declarations?.some((declaration) => {
      const declarationFile = declaration.getSourceFile().fileName;
      if (transport === "requestJson") {
        return declarationSourcePath(declaration) === "shared/api/transport.ts";
      }
      return declarationFile.endsWith("lib.dom.d.ts");
    });
    return ownsDeclaration ? transport : null;
  }

  function rawTransportSymbol(node: ts.Node): string | null {
    return rawTransportNameForSymbol(resolvedSymbol(node));
  }

  function constantStringValue(
    value: ts.Expression,
    seen = new Set<ts.Symbol>(),
  ): string | null {
    while (
      ts.isParenthesizedExpression(value) ||
      ts.isAsExpression(value) ||
      ts.isSatisfiesExpression(value) ||
      ts.isNonNullExpression(value)
    ) {
      value = value.expression;
    }
    if (ts.isStringLiteralLike(value)) {
      return value.text;
    }
    if (ts.isConditionalExpression(value)) {
      const whenTrue = constantStringValue(value.whenTrue, seen);
      const whenFalse = constantStringValue(value.whenFalse, seen);
      return whenTrue === whenFalse ? whenTrue : null;
    }
    if (!ts.isIdentifier(value)) {
      return null;
    }
    const symbol = resolvedSymbol(value);
    if (!symbol || seen.has(symbol)) {
      return null;
    }
    seen.add(symbol);
    for (const declaration of symbol.declarations ?? []) {
      if (
        ts.isVariableDeclaration(declaration) &&
        declaration.initializer &&
        ts.isVariableDeclarationList(declaration.parent) &&
        (declaration.parent.flags & ts.NodeFlags.Const) !== 0
      ) {
        return constantStringValue(declaration.initializer, seen);
      }
    }
    return null;
  }

  function computedRawTransportAccess(
    node: ts.ElementAccessExpression,
  ): string | null {
    const receiverType = checker.getTypeAtLocation(node.expression);
    const exposedTransports = [...RAW_TRANSPORT_REFERENCES].filter(
      (transport) =>
        rawTransportNameForSymbol(
          resolvedAliasSymbol(
            checker.getPropertyOfType(receiverType, transport),
          ),
        ) === transport,
    );
    if (exposedTransports.length === 0) {
      return null;
    }
    const key = constantStringValue(node.argumentExpression);
    if (key === null) {
      return "[unresolved]";
    }
    return exposedTransports.includes(key) ? key : null;
  }

  function isTypeOnlyReference(node: ts.Node): boolean {
    let current: ts.Node | undefined = node.parent;
    while (current && !ts.isSourceFile(current)) {
      if (ts.isTypeNode(current)) {
        return true;
      }
      if (ts.isImportSpecifier(current)) {
        const importClause = current.parent.parent;
        return (
          current.isTypeOnly ||
          (ts.isImportClause(importClause) && importClause.isTypeOnly)
        );
      }
      if (ts.isExportSpecifier(current)) {
        const exportDeclaration = current.parent.parent;
        return (
          current.isTypeOnly ||
          (ts.isExportDeclaration(exportDeclaration) &&
            exportDeclaration.isTypeOnly)
        );
      }
      current = current.parent;
    }
    return false;
  }

  function isIdentitySpecifier(node: ts.Node, symbolName: string): boolean {
    const specifier =
      ts.isImportSpecifier(node.parent) || ts.isExportSpecifier(node.parent)
        ? node.parent
        : null;
    if (!specifier) {
      return false;
    }
    return (
      (specifier.propertyName ?? specifier.name).text === symbolName &&
      specifier.name.text === symbolName
    );
  }

  function isDirectOwnedReference(node: ts.Node, symbolName: string): boolean {
    if (isIdentitySpecifier(node, symbolName)) {
      return true;
    }
    const parent = node.parent;
    if (
      (ts.isFunctionDeclaration(parent) || ts.isFunctionExpression(parent)) &&
      parent.name === node
    ) {
      return true;
    }

    let expression: ts.Node = node;
    if (
      (ts.isPropertyAccessExpression(parent) && parent.name === node) ||
      (ts.isElementAccessExpression(parent) &&
        parent.argumentExpression === node)
    ) {
      expression = parent;
    }
    while (ts.isParenthesizedExpression(expression.parent)) {
      expression = expression.parent;
    }
    return (
      (ts.isCallExpression(expression.parent) ||
        ts.isNewExpression(expression.parent)) &&
      expression.parent.expression === expression
    );
  }

  function moduleExposesBoundary(node: ts.Node): boolean {
    const moduleSymbol = resolvedSymbol(node);
    if (!moduleSymbol || (moduleSymbol.flags & ts.SymbolFlags.Module) === 0) {
      return false;
    }
    return checker.getExportsOfModule(moduleSymbol).some((exportedSymbol) => {
      const symbol = resolvedAliasSymbol(exportedSymbol);
      return (
        mutationNameForSymbol(symbol) !== null ||
        rawTransportNameForSymbol(symbol) !== null
      );
    });
  }

  function templateImportTargets(
    importer: string,
    template: ts.TemplateExpression,
  ): string[] {
    let pattern =
      template.head.text +
      template.templateSpans.map((span) => "*" + span.literal.text).join("");
    let cwd = dirname(importer);
    if (pattern.startsWith("/src/")) {
      cwd = SOURCE_ROOT;
      pattern = pattern.slice("/src/".length);
    } else if (!pattern.startsWith(".")) {
      return [];
    }
    return globSync(pattern, {
      absolute: true,
      cwd,
      onlyFiles: true,
    });
  }

  function reflectedBoundaryName(node: ts.CallExpression): string | null {
    if (
      !ts.isPropertyAccessExpression(node.expression) ||
      node.expression.name.text !== "get" ||
      !ts.isIdentifier(node.expression.expression) ||
      node.arguments.length < 2 ||
      !ts.isStringLiteralLike(node.arguments[1])
    ) {
      return null;
    }
    const reflectSymbol = resolvedSymbol(node.expression.expression);
    const isGlobalReflect = reflectSymbol?.declarations?.some((declaration) =>
      declaration.getSourceFile().fileName.endsWith("lib.es2015.reflect.d.ts"),
    );
    if (!isGlobalReflect) {
      return null;
    }
    const targetType = checker.getTypeAtLocation(node.arguments[0]);
    const propertySymbol = resolvedAliasSymbol(
      checker.getPropertyOfType(targetType, node.arguments[1].text),
    );
    return (
      mutationNameForSymbol(propertySymbol) ??
      rawTransportNameForSymbol(propertySymbol)
    );
  }

  type CallableImplementation =
    | ts.ArrowFunction
    | ts.CallExpression
    | ts.ClassStaticBlockDeclaration
    | ts.ConstructorDeclaration
    | ts.FunctionDeclaration
    | ts.FunctionExpression
    | ts.GetAccessorDeclaration
    | ts.MethodDeclaration
    | ts.PropertyDeclaration
    | ts.SetAccessorDeclaration;

  function callableImplementation(
    symbol: ts.Symbol | null,
    seen = new Set<ts.Symbol>(),
  ): CallableImplementation | null {
    if (!symbol || seen.has(symbol)) {
      return null;
    }
    seen.add(symbol);
    for (const declaration of symbol?.declarations ?? []) {
      if (ts.isFunctionExpression(declaration)) {
        return declaration;
      }
      if (
        (ts.isFunctionDeclaration(declaration) ||
          ts.isMethodDeclaration(declaration) ||
          ts.isGetAccessorDeclaration(declaration) ||
          ts.isSetAccessorDeclaration(declaration) ||
          ts.isConstructorDeclaration(declaration)) &&
        declaration.body
      ) {
        return declaration;
      }
      if (
        ts.isVariableDeclaration(declaration) &&
        declaration.initializer &&
        (ts.isArrowFunction(declaration.initializer) ||
          ts.isFunctionExpression(declaration.initializer))
      ) {
        return declaration.initializer;
      }
      if (
        ts.isVariableDeclaration(declaration) &&
        declaration.initializer &&
        ts.isCallExpression(declaration.initializer) &&
        checker.getSignaturesOfType(
          checker.getTypeAtLocation(declaration.name),
          ts.SignatureKind.Call,
        ).length > 0
      ) {
        return declaration.initializer;
      }
      if (ts.isPropertyDeclaration(declaration) && declaration.initializer) {
        return ts.isArrowFunction(declaration.initializer) ||
          ts.isFunctionExpression(declaration.initializer)
          ? declaration.initializer
          : declaration;
      }
      if (ts.isVariableDeclaration(declaration) && declaration.initializer) {
        const implementation = callableImplementation(
          resolvedSymbol(declaration.initializer),
          seen,
        );
        if (implementation) {
          return implementation;
        }
      }
      if (
        ts.isPropertyAssignment(declaration) &&
        (ts.isArrowFunction(declaration.initializer) ||
          ts.isFunctionExpression(declaration.initializer))
      ) {
        return declaration.initializer;
      }
      if (ts.isPropertyAssignment(declaration)) {
        const implementation = callableImplementation(
          resolvedSymbol(declaration.initializer),
          seen,
        );
        if (implementation) {
          return implementation;
        }
      }
      if (ts.isShorthandPropertyAssignment(declaration)) {
        const implementation = callableImplementation(
          resolvedAliasSymbol(
            checker.getShorthandAssignmentValueSymbol(declaration),
          ),
          seen,
        );
        if (implementation) {
          return implementation;
        }
      }
    }
    return null;
  }

  function callReference(node: ts.CallExpression): ts.Node {
    return ts.isPropertyAccessExpression(node.expression)
      ? node.expression.name
      : ts.isElementAccessExpression(node.expression)
        ? node.expression.argumentExpression
        : node.expression;
  }

  function invocationHelperReceiver(
    node: ts.CallExpression,
  ): ts.Expression | null {
    if (
      ts.isPropertyAccessExpression(node.expression) ||
      ts.isElementAccessExpression(node.expression)
    ) {
      const helperName = ts.isPropertyAccessExpression(node.expression)
        ? node.expression.name.text
        : ts.isStringLiteralLike(node.expression.argumentExpression)
          ? node.expression.argumentExpression.text
          : null;
      if (["apply", "bind", "call"].includes(helperName ?? "")) {
        if (
          ts.isPropertyAccessExpression(node.expression) &&
          ts.isIdentifier(node.expression.expression) &&
          node.expression.expression.text === "Reflect" &&
          helperName === "apply"
        ) {
          const reflectSymbol = resolvedSymbol(node.expression.expression);
          const isGlobalReflect = reflectSymbol?.declarations?.some(
            (declaration) =>
              declaration
                .getSourceFile()
                .fileName.endsWith("lib.es2015.reflect.d.ts"),
          );
          return isGlobalReflect ? (node.arguments[0] ?? null) : null;
        }
        return node.expression.expression;
      }
    }
    return null;
  }

  type RequestMethodState = "absent" | "read" | "write";

  function methodValueState(value: ts.Expression): RequestMethodState {
    return ts.isStringLiteralLike(value) &&
      ["GET", "HEAD"].includes(value.text.toUpperCase())
      ? "read"
      : "write";
  }

  function composeMethodStates(
    currentStates: Set<RequestMethodState>,
    overrideStates: Set<RequestMethodState>,
  ): Set<RequestMethodState> {
    const composed = new Set<RequestMethodState>();
    for (const current of currentStates) {
      for (const override of overrideStates) {
        composed.add(override === "absent" ? current : override);
      }
    }
    return composed;
  }

  function requestMethodStates(value: ts.Expression): Set<RequestMethodState> {
    while (
      ts.isParenthesizedExpression(value) ||
      ts.isAsExpression(value) ||
      ts.isSatisfiesExpression(value)
    ) {
      value = value.expression;
    }
    if (ts.isConditionalExpression(value)) {
      return new Set([
        ...requestMethodStates(value.whenTrue),
        ...requestMethodStates(value.whenFalse),
      ]);
    }
    if (
      (ts.isIdentifier(value) && value.text === "undefined") ||
      ts.isVoidExpression(value)
    ) {
      return new Set(["absent"]);
    }
    if (!ts.isObjectLiteralExpression(value)) {
      return new Set(["write"]);
    }

    let states = new Set<RequestMethodState>(["absent"]);
    for (const property of value.properties) {
      if (ts.isSpreadAssignment(property)) {
        states = composeMethodStates(
          states,
          requestMethodStates(property.expression),
        );
        continue;
      }
      if (ts.isComputedPropertyName(property.name)) {
        states = new Set(["write"]);
        continue;
      }
      const propertyName =
        ts.isIdentifier(property.name) || ts.isStringLiteralLike(property.name)
          ? property.name.text
          : null;
      if (propertyName !== "method") {
        continue;
      }
      states = new Set([
        ts.isPropertyAssignment(property)
          ? methodValueState(property.initializer)
          : "write",
      ]);
    }
    return states;
  }

  function requestOptionsWrite(value: ts.Expression): boolean {
    return requestMethodStates(value).has("write");
  }

  function isGlobalDomSymbol(symbol: ts.Symbol | null, name: string): boolean {
    return (
      symbol?.getName() === name &&
      (symbol.declarations?.some((declaration) =>
        declaration.getSourceFile().fileName.endsWith("lib.dom.d.ts"),
      ) ??
        false)
    );
  }

  function typeContainsGlobalDomType(type: ts.Type, name: string): boolean {
    if (type.isUnionOrIntersection()) {
      return type.types.some((member) =>
        typeContainsGlobalDomType(member, name),
      );
    }
    return isGlobalDomSymbol(
      resolvedAliasSymbol(type.aliasSymbol ?? type.getSymbol()),
      name,
    );
  }

  function requestInputMethodStates(
    value: ts.Expression | undefined,
  ): Set<RequestMethodState> {
    if (!value) {
      return new Set(["absent"]);
    }
    while (
      ts.isParenthesizedExpression(value) ||
      ts.isAsExpression(value) ||
      ts.isSatisfiesExpression(value)
    ) {
      value = value.expression;
    }
    if (
      ts.isNewExpression(value) &&
      isGlobalDomSymbol(resolvedSymbol(value.expression), "Request")
    ) {
      return composeMethodStates(
        requestInputMethodStates(value.arguments?.[0]),
        value.arguments?.[1]
          ? requestMethodStates(value.arguments[1])
          : new Set(["absent"]),
      );
    }
    return typeContainsGlobalDomType(
      checker.getTypeAtLocation(value),
      "Request",
    )
      ? new Set(["write"])
      : new Set(["absent"]);
  }

  function rawCallWrites(node: ts.CallExpression): boolean {
    const transport = rawTransportSymbol(callReference(node));
    if (!transport) {
      return false;
    }
    if (transport === "sendBeacon") {
      return true;
    }
    if (transport === "fetch") {
      return composeMethodStates(
        requestInputMethodStates(node.arguments[0]),
        node.arguments[1]
          ? requestMethodStates(node.arguments[1])
          : new Set(["absent"]),
      ).has("write");
    }
    const options = node.arguments[1];
    return transport === "requestJson" && options
      ? requestOptionsWrite(options)
      : false;
  }

  function xmlHttpRequestWrites(callable: CallableImplementation): boolean {
    const operations = new Map<
      ts.Symbol,
      { send: boolean; writeOpen: boolean }
    >();
    const receiverAliases = new Map<ts.Symbol, ts.Symbol>();

    function collectReceiverAliases(node: ts.Node): void {
      let target: ts.Node | null = null;
      let value: ts.Expression | null = null;
      if (
        ts.isVariableDeclaration(node) &&
        ts.isIdentifier(node.name) &&
        node.initializer
      ) {
        target = node.name;
        value = node.initializer;
      } else if (
        ts.isBinaryExpression(node) &&
        node.operatorToken.kind === ts.SyntaxKind.EqualsToken
      ) {
        target = node.left;
        value = node.right;
      }
      if (
        target &&
        value &&
        typeContainsGlobalDomType(
          checker.getTypeAtLocation(target),
          "XMLHttpRequest",
        ) &&
        typeContainsGlobalDomType(
          checker.getTypeAtLocation(value),
          "XMLHttpRequest",
        )
      ) {
        const targetSymbol = resolvedSymbol(target);
        const valueSymbol = resolvedSymbol(value);
        if (targetSymbol && valueSymbol && targetSymbol !== valueSymbol) {
          receiverAliases.set(targetSymbol, valueSymbol);
        }
      }
      ts.forEachChild(node, collectReceiverAliases);
    }

    function canonicalReceiverSymbol(symbol: ts.Symbol): ts.Symbol {
      const seen = new Set<ts.Symbol>();
      while (receiverAliases.has(symbol) && !seen.has(symbol)) {
        seen.add(symbol);
        symbol = receiverAliases.get(symbol) ?? symbol;
      }
      return symbol;
    }

    function visit(node: ts.Node): void {
      if (
        ts.isCallExpression(node) &&
        (ts.isPropertyAccessExpression(node.expression) ||
          ts.isElementAccessExpression(node.expression))
      ) {
        const receiver = node.expression.expression;
        if (
          typeContainsGlobalDomType(
            checker.getTypeAtLocation(receiver),
            "XMLHttpRequest",
          )
        ) {
          const receiverSymbol = resolvedSymbol(receiver);
          const methodName = ts.isPropertyAccessExpression(node.expression)
            ? node.expression.name.text
            : ts.isStringLiteralLike(node.expression.argumentExpression)
              ? node.expression.argumentExpression.text
              : null;
          if (
            receiverSymbol &&
            (methodName === "open" || methodName === "send")
          ) {
            const canonicalSymbol = canonicalReceiverSymbol(receiverSymbol);
            const operation = operations.get(canonicalSymbol) ?? {
              send: false,
              writeOpen: false,
            };
            if (methodName === "send") {
              operation.send = true;
            } else {
              operation.writeOpen = node.arguments[0]
                ? methodValueState(node.arguments[0]) === "write"
                : true;
            }
            operations.set(canonicalSymbol, operation);
          }
        }
      }
      ts.forEachChild(node, visit);
    }

    collectReceiverAliases(callable);
    visit(callable);
    return [...operations.values()].some((operation) => operation.send);
  }

  const writeBearingCallables = new Map<CallableImplementation, boolean>();
  const cycleTaintedCallables = new Set<CallableImplementation>();

  function argumentCallableWrites(
    argument: ts.Node,
    active: Set<CallableImplementation>,
  ): boolean {
    let writes = false;

    function visit(node: ts.Node): void {
      if (writes) {
        return;
      }
      if (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) {
        writes = callableWrites(node, active);
        return;
      }
      if (
        ts.isIdentifier(node) ||
        ts.isPropertyAccessExpression(node) ||
        ts.isElementAccessExpression(node)
      ) {
        const implementation = callableImplementation(resolvedSymbol(node));
        if (implementation) {
          writes = callableWrites(implementation, active);
          if (writes || !ts.isIdentifier(node)) {
            return;
          }
        }
      }
      ts.forEachChild(node, visit);
    }

    visit(argument);
    return writes;
  }

  function constructorImplementations(
    expression: ts.Expression,
    seen = new Set<ts.Symbol>(),
  ): CallableImplementation[] {
    const implementations: CallableImplementation[] = [];
    const initialSymbol = resolvedSymbol(expression);

    function collectClass(
      declaration: ts.ClassDeclaration | ts.ClassExpression,
    ): void {
      const classSymbol = resolvedSymbol(declaration.name ?? declaration);
      if (classSymbol && seen.has(classSymbol)) {
        return;
      }
      if (classSymbol) {
        seen.add(classSymbol);
      }
      for (const member of declaration.members) {
        if (ts.isConstructorDeclaration(member) && member.body) {
          implementations.push(member);
        }
      }
      const classType = checker.getTypeAtLocation(declaration);
      if ((classType.flags & ts.TypeFlags.Object) !== 0) {
        for (const baseType of checker.getBaseTypes(
          classType as ts.InterfaceType,
        )) {
          const baseSymbol = resolvedAliasSymbol(
            baseType.aliasSymbol ?? baseType.getSymbol(),
          );
          collectSymbol(baseSymbol);
        }
      }
    }

    function collectSymbol(symbol: ts.Symbol | null): void {
      if (!symbol || seen.has(symbol)) {
        return;
      }
      const classDeclarations = (symbol.declarations ?? []).filter(
        (
          declaration,
        ): declaration is ts.ClassDeclaration | ts.ClassExpression =>
          ts.isClassDeclaration(declaration) ||
          ts.isClassExpression(declaration),
      );
      if (classDeclarations.length > 0) {
        classDeclarations.forEach(collectClass);
        return;
      }
      seen.add(symbol);
      const implementation = callableImplementation(symbol);
      if (implementation) {
        implementations.push(implementation);
      }
    }

    if (ts.isClassExpression(expression)) {
      collectClass(expression);
    } else {
      collectSymbol(initialSymbol);
    }
    return implementations;
  }

  function callableWrites(
    callable: CallableImplementation,
    active = new Set<CallableImplementation>(),
  ): boolean {
    const cached = writeBearingCallables.get(callable);
    if (cached !== undefined) {
      return cached;
    }
    if (active.has(callable)) {
      active.forEach((activeCallable) =>
        cycleTaintedCallables.add(activeCallable),
      );
      return false;
    }
    active.add(callable);
    let writes = xmlHttpRequestWrites(callable);

    function visit(node: ts.Node): void {
      if (writes) {
        return;
      }
      if (ts.isCallExpression(node)) {
        const reference = callReference(node);
        const rawTransport = rawTransportSymbol(reference);
        if (rawTransport) {
          writes = rawCallWrites(node);
        } else {
          const localCallable = callableImplementation(
            resolvedSymbol(reference),
          );
          const receiver = invocationHelperReceiver(node);
          const receiverCallable = receiver
            ? callableImplementation(resolvedSymbol(receiver))
            : null;
          writes =
            mutationSymbol(reference) !== null ||
            (localCallable !== null && callableWrites(localCallable, active)) ||
            (receiverCallable !== null &&
              callableWrites(receiverCallable, active));
          if (!writes) {
            writes = node.arguments.some((argument) =>
              argumentCallableWrites(argument, active),
            );
          }
        }
      }
      if (ts.isNewExpression(node)) {
        writes = constructorImplementations(node.expression).some(
          (implementation) => callableWrites(implementation, active),
        );
        if (!writes) {
          writes = (node.arguments ?? []).some((argument) =>
            argumentCallableWrites(argument, active),
          );
        }
      }
      ts.forEachChild(node, visit);
    }

    visit(callable);
    active.delete(callable);
    if (writes || !cycleTaintedCallables.has(callable)) {
      writeBearingCallables.set(callable, writes);
    }
    return writes;
  }

  interface ExportedCallable {
    callable: CallableImplementation;
    label: string;
    topLevel: boolean;
  }

  function staticMemberName(name: ts.PropertyName): string {
    return ts.isIdentifier(name) || ts.isStringLiteralLike(name)
      ? name.text
      : "[computed]";
  }

  function callableAliasMembers(
    symbol: ts.Symbol | null,
    label: string,
    seen: Set<ts.Symbol>,
  ): ExportedCallable[] {
    if (!symbol || seen.has(symbol)) {
      return [];
    }
    const implementation = callableImplementation(symbol);
    if (implementation) {
      return [{ callable: implementation, label, topLevel: false }];
    }
    seen.add(symbol);
    const members: ExportedCallable[] = [];
    for (const declaration of symbol.declarations ?? []) {
      if (ts.isVariableDeclaration(declaration) && declaration.initializer) {
        if (
          ts.isObjectLiteralExpression(declaration.initializer) ||
          ts.isClassExpression(declaration.initializer)
        ) {
          members.push(
            ...callableMembers(declaration.initializer, label, seen),
          );
        } else {
          members.push(
            ...callableAliasMembers(
              resolvedSymbol(declaration.initializer),
              label,
              seen,
            ),
          );
        }
      } else if (ts.isClassDeclaration(declaration)) {
        members.push(...callableMembers(declaration, label, seen));
      }
    }
    return members;
  }

  function typedValueCallables(
    value: ts.Expression,
    label: string,
    seen = new Set<ts.Symbol>(),
  ): ExportedCallable[] {
    const members: ExportedCallable[] = [];
    const valueType = checker.getTypeAtLocation(value);
    members.push(...reachableTypeCallables(valueType, label, seen));

    if (ts.isArrayLiteralExpression(value)) {
      for (const element of value.elements) {
        if (ts.isOmittedExpression(element)) {
          continue;
        }
        members.push(
          ...nestedValueCallables(
            ts.isSpreadElement(element) ? element.expression : element,
            label + "[]",
            seen,
          ),
        );
      }
    }

    if (ts.isNewExpression(value)) {
      if (ts.isClassExpression(value.expression)) {
        members.push(...callableMembers(value.expression, label, seen));
      } else {
        const constructorSymbol = resolvedSymbol(value.expression);
        for (const declaration of constructorSymbol?.declarations ?? []) {
          if (
            ts.isClassDeclaration(declaration) ||
            ts.isClassExpression(declaration)
          ) {
            members.push(...callableMembers(declaration, label, seen));
          }
        }
      }
    }

    const valueSymbol = resolvedSymbol(value);
    if (valueSymbol && !seen.has(valueSymbol)) {
      seen.add(valueSymbol);
      for (const declaration of valueSymbol.declarations ?? []) {
        if (
          ts.isVariableDeclaration(declaration) &&
          declaration.initializer &&
          declaration.initializer !== value
        ) {
          members.push(
            ...typedValueCallables(declaration.initializer, label, seen),
          );
        }
      }
    }
    return members;
  }

  function reachableTypeCallables(
    type: ts.Type,
    label: string,
    seenSymbols: Set<ts.Symbol>,
    seenTypes = new Set<ts.Type>(),
  ): ExportedCallable[] {
    if (seenTypes.has(type)) {
      return [];
    }
    seenTypes.add(type);
    if (type.isUnionOrIntersection()) {
      return type.types.flatMap((member) =>
        reachableTypeCallables(member, label, seenSymbols, seenTypes),
      );
    }

    const members: ExportedCallable[] = [];
    for (const property of checker.getPropertiesOfType(type)) {
      const propertyLabel = label + "." + property.getName();
      members.push(
        ...callableAliasMembers(
          resolvedAliasSymbol(property),
          propertyLabel,
          seenSymbols,
        ),
      );
      const propertyDeclaration =
        property.valueDeclaration ?? property.declarations?.[0];
      if (propertyDeclaration) {
        const propertyType = checker.getTypeOfSymbolAtLocation(
          property,
          propertyDeclaration,
        );
        if (hasProductionObjectDeclaration(propertyType)) {
          members.push(
            ...reachableTypeCallables(
              propertyType,
              propertyLabel,
              seenSymbols,
              seenTypes,
            ),
          );
        }
      }
    }
    members.push(...collectionTypeCallables(type, label + "[]"));

    if (
      (type.flags & ts.TypeFlags.Object) !== 0 &&
      ((type as ts.ObjectType).objectFlags & ts.ObjectFlags.Reference) !== 0
    ) {
      for (const typeArgument of checker.getTypeArguments(
        type as ts.TypeReference,
      )) {
        members.push(
          ...reachableTypeCallables(
            typeArgument,
            label + ".[value]",
            seenSymbols,
            seenTypes,
          ),
        );
      }
    }

    for (const promisedType of promisedValueTypes(type)) {
      members.push(
        ...reachableTypeCallables(
          promisedType,
          label + ".[await]",
          seenSymbols,
          seenTypes,
        ),
      );
    }
    return members;
  }

  function hasProductionObjectDeclaration(type: ts.Type): boolean {
    if (type.isUnionOrIntersection()) {
      return type.types.some(hasProductionObjectDeclaration);
    }
    if ((type.flags & ts.TypeFlags.Object) === 0) {
      return false;
    }
    const symbol = resolvedAliasSymbol(type.aliasSymbol ?? type.getSymbol());
    return (
      symbol?.declarations?.some(
        (declaration) => declarationSourcePath(declaration) !== null,
      ) ?? false
    );
  }

  function promisedValueTypes(type: ts.Type): ts.Type[] {
    const thenSymbol = checker.getPropertyOfType(type, "then");
    const thenDeclaration =
      thenSymbol?.valueDeclaration ?? thenSymbol?.declarations?.[0];
    if (!thenSymbol || !thenDeclaration) {
      return [];
    }
    const thenType = checker.getTypeOfSymbolAtLocation(
      thenSymbol,
      thenDeclaration,
    );
    const callbackTypes: ts.Type[] = [];
    for (const signature of checker.getSignaturesOfType(
      thenType,
      ts.SignatureKind.Call,
    )) {
      const callbackSymbol = signature.parameters[0];
      const callbackDeclaration =
        callbackSymbol?.valueDeclaration ?? callbackSymbol?.declarations?.[0];
      if (callbackSymbol && callbackDeclaration) {
        callbackTypes.push(
          checker.getTypeOfSymbolAtLocation(
            callbackSymbol,
            callbackDeclaration,
          ),
        );
      }
    }

    const promisedTypes: ts.Type[] = [];
    function inspectCallback(callbackType: ts.Type): void {
      if (callbackType.isUnionOrIntersection()) {
        callbackType.types.forEach(inspectCallback);
        return;
      }
      for (const signature of checker.getSignaturesOfType(
        callbackType,
        ts.SignatureKind.Call,
      )) {
        const valueSymbol = signature.parameters[0];
        const valueDeclaration =
          valueSymbol?.valueDeclaration ?? valueSymbol?.declarations?.[0];
        if (valueSymbol && valueDeclaration) {
          promisedTypes.push(
            checker.getTypeOfSymbolAtLocation(valueSymbol, valueDeclaration),
          );
        }
      }
    }
    callbackTypes.forEach(inspectCallback);
    return promisedTypes;
  }

  function nestedValueCallables(
    value: ts.Expression,
    label: string,
    seen: Set<ts.Symbol>,
  ): ExportedCallable[] {
    const members: ExportedCallable[] = [];
    const implementation =
      ts.isArrowFunction(value) || ts.isFunctionExpression(value)
        ? value
        : callableImplementation(resolvedSymbol(value));
    if (implementation) {
      members.push({ callable: implementation, label, topLevel: false });
    }
    members.push(...typedValueCallables(value, label, seen));
    return members;
  }

  function collectionTypeCallables(
    type: ts.Type,
    label: string,
    seen = new Set<ts.Type>(),
  ): ExportedCallable[] {
    if (seen.has(type)) {
      return [];
    }
    seen.add(type);
    if (type.isUnionOrIntersection()) {
      return type.types.flatMap((member) =>
        collectionTypeCallables(member, label, seen),
      );
    }
    const collectionName = resolvedAliasSymbol(
      type.aliasSymbol ?? type.getSymbol(),
    )?.getName();
    const isCollection =
      checker.isArrayType(type) ||
      checker.isTupleType(type) ||
      [
        "Array",
        "Map",
        "ReadonlyArray",
        "ReadonlyMap",
        "ReadonlySet",
        "Set",
        "WeakMap",
        "WeakSet",
      ].includes(collectionName ?? "");
    if (!isCollection) {
      return [];
    }

    const members: ExportedCallable[] = [];
    for (const typeArgument of checker.getTypeArguments(
      type as ts.TypeReference,
    )) {
      for (const signature of checker.getSignaturesOfType(
        typeArgument,
        ts.SignatureKind.Call,
      )) {
        const declaration = signature.declaration;
        if (
          declaration &&
          (ts.isArrowFunction(declaration) ||
            ts.isFunctionDeclaration(declaration) ||
            ts.isFunctionExpression(declaration) ||
            ts.isMethodDeclaration(declaration))
        ) {
          members.push({ callable: declaration, label, topLevel: false });
        }
      }
      members.push(...collectionTypeCallables(typeArgument, label, seen));
    }
    return members;
  }

  function callableMembers(
    value: ts.Expression | ts.ClassDeclaration,
    label: string,
    seen = new Set<ts.Symbol>(),
  ): ExportedCallable[] {
    const members: ExportedCallable[] = [];
    if (ts.isClassDeclaration(value) || ts.isClassExpression(value)) {
      const classSymbol = resolvedSymbol(value.name ?? value);
      if (classSymbol && seen.has(classSymbol)) {
        return members;
      }
      if (classSymbol) {
        seen.add(classSymbol);
      }
    }
    const declarations = ts.isObjectLiteralExpression(value)
      ? value.properties
      : ts.isClassDeclaration(value) || ts.isClassExpression(value)
        ? value.members
        : [];
    for (const declaration of declarations) {
      if (
        ts.isMethodDeclaration(declaration) ||
        ts.isGetAccessorDeclaration(declaration) ||
        ts.isSetAccessorDeclaration(declaration)
      ) {
        members.push({
          callable: declaration,
          label: label + "." + staticMemberName(declaration.name),
          topLevel: false,
        });
      } else if (ts.isConstructorDeclaration(declaration)) {
        members.push({
          callable: declaration,
          label: label + ".constructor",
          topLevel: false,
        });
      } else if (ts.isClassStaticBlockDeclaration(declaration)) {
        members.push({
          callable: declaration,
          label: label + ".[static]",
          topLevel: false,
        });
      } else if (
        (ts.isPropertyAssignment(declaration) ||
          ts.isPropertyDeclaration(declaration)) &&
        declaration.initializer &&
        (ts.isArrowFunction(declaration.initializer) ||
          ts.isFunctionExpression(declaration.initializer))
      ) {
        members.push({
          callable: declaration.initializer,
          label: label + "." + staticMemberName(declaration.name),
          topLevel: false,
        });
      } else if (ts.isShorthandPropertyAssignment(declaration)) {
        members.push(
          ...callableAliasMembers(
            resolvedAliasSymbol(
              checker.getShorthandAssignmentValueSymbol(declaration),
            ),
            label + "." + declaration.name.text,
            seen,
          ),
        );
      } else if (ts.isSpreadAssignment(declaration)) {
        members.push(
          ...typedValueCallables(declaration.expression, label, seen),
        );
      } else if (
        (ts.isPropertyAssignment(declaration) ||
          ts.isPropertyDeclaration(declaration)) &&
        declaration.initializer &&
        !ts.isObjectLiteralExpression(declaration.initializer) &&
        !ts.isClassExpression(declaration.initializer)
      ) {
        members.push(
          ...callableAliasMembers(
            resolvedSymbol(declaration.initializer),
            label + "." + staticMemberName(declaration.name),
            seen,
          ),
        );
        if (ts.isPropertyDeclaration(declaration)) {
          members.push({
            callable: declaration,
            label: label + "." + staticMemberName(declaration.name),
            topLevel: false,
          });
        }
      } else if (
        (ts.isPropertyAssignment(declaration) ||
          ts.isPropertyDeclaration(declaration)) &&
        declaration.initializer &&
        (ts.isObjectLiteralExpression(declaration.initializer) ||
          ts.isClassExpression(declaration.initializer))
      ) {
        members.push(
          ...callableMembers(
            declaration.initializer,
            label + "." + staticMemberName(declaration.name),
            seen,
          ),
        );
      }
    }
    if (ts.isClassDeclaration(value) || ts.isClassExpression(value)) {
      const classType = checker.getTypeAtLocation(value);
      if ((classType.flags & ts.TypeFlags.Object) !== 0) {
        for (const baseType of checker.getBaseTypes(
          classType as ts.InterfaceType,
        )) {
          const baseSymbol = resolvedAliasSymbol(
            baseType.aliasSymbol ?? baseType.getSymbol(),
          );
          for (const declaration of baseSymbol?.declarations ?? []) {
            if (
              ts.isClassDeclaration(declaration) ||
              ts.isClassExpression(declaration)
            ) {
              members.push(...callableMembers(declaration, label, seen));
            }
          }
        }
      }
    }
    return members;
  }

  function returnedValueCallables(
    callable: CallableImplementation,
    label: string,
  ): ExportedCallable[] {
    const returned: ExportedCallable[] = [];

    function inspect(value: ts.Expression): void {
      while (
        ts.isParenthesizedExpression(value) ||
        ts.isAsExpression(value) ||
        ts.isSatisfiesExpression(value) ||
        ts.isAwaitExpression(value)
      ) {
        value = value.expression;
      }
      if (ts.isConditionalExpression(value)) {
        inspect(value.whenTrue);
        inspect(value.whenFalse);
        return;
      }
      const returnLabel = label + ".[return]";
      if (ts.isArrowFunction(value) || ts.isFunctionExpression(value)) {
        returned.push({ callable: value, label: returnLabel, topLevel: false });
      } else {
        const implementation = callableImplementation(resolvedSymbol(value));
        if (implementation) {
          returned.push({
            callable: implementation,
            label: returnLabel,
            topLevel: false,
          });
        }
      }
      returned.push(...typedValueCallables(value, returnLabel));
    }

    if (ts.isArrowFunction(callable) && !ts.isBlock(callable.body)) {
      inspect(callable.body);
      return returned;
    }

    function visit(node: ts.Node): void {
      if (node !== callable && ts.isFunctionLike(node)) {
        return;
      }
      if (ts.isReturnStatement(node) && node.expression) {
        inspect(node.expression);
        return;
      }
      ts.forEachChild(node, visit);
    }

    visit(callable);
    return returned;
  }

  function callExpressionCallables(
    call: ts.CallExpression,
    label: string,
  ): ExportedCallable[] {
    const callables: ExportedCallable[] = [];
    const seen = new Set<CallableImplementation>();

    function collect(value: ts.Node): void {
      if (ts.isArrowFunction(value) || ts.isFunctionExpression(value)) {
        if (!seen.has(value)) {
          seen.add(value);
          callables.push({ callable: value, label, topLevel: true });
        }
        return;
      }
      if (
        ts.isIdentifier(value) ||
        ts.isPropertyAccessExpression(value) ||
        ts.isElementAccessExpression(value)
      ) {
        const implementation = callableImplementation(resolvedSymbol(value));
        if (implementation && !seen.has(implementation)) {
          seen.add(implementation);
          callables.push({ callable: implementation, label, topLevel: true });
        }
      }
      ts.forEachChild(value, collect);
    }

    const invoked = callableImplementation(resolvedSymbol(callReference(call)));
    if (invoked) {
      seen.add(invoked);
      callables.push({ callable: invoked, label, topLevel: true });
    }
    if (
      ts.isPropertyAccessExpression(call.expression) ||
      ts.isElementAccessExpression(call.expression)
    ) {
      collect(call.expression.expression);
    }
    for (const argument of call.arguments) {
      collect(argument);
    }
    return callables;
  }

  function destructuredExportCallables(
    declaration: ts.BindingElement,
    exportName: string,
  ): ExportedCallable[] {
    const callables: ExportedCallable[] = [];
    const bindingPattern = declaration.parent;
    const variableDeclaration = bindingPattern.parent;
    if (
      !ts.isVariableDeclaration(variableDeclaration) ||
      !variableDeclaration.initializer
    ) {
      return callables;
    }

    function addExpression(value: ts.Expression): void {
      const implementation =
        ts.isArrowFunction(value) || ts.isFunctionExpression(value)
          ? value
          : callableImplementation(resolvedSymbol(value));
      if (implementation) {
        callables.push({
          callable: implementation,
          label: exportName,
          topLevel: true,
        });
      }
      callables.push(...typedValueCallables(value, exportName));
    }

    if (declaration.initializer) {
      addExpression(declaration.initializer);
    }
    if (declaration.dotDotDotToken) {
      callables.push(
        ...typedValueCallables(variableDeclaration.initializer, exportName),
      );
      return callables;
    }
    if (ts.isObjectBindingPattern(bindingPattern)) {
      const propertyName = declaration.propertyName ?? declaration.name;
      const staticName =
        ts.isIdentifier(propertyName) || ts.isStringLiteralLike(propertyName)
          ? propertyName.text
          : null;
      if (staticName) {
        const sourceType = checker.getTypeAtLocation(
          variableDeclaration.initializer,
        );
        const property = resolvedAliasSymbol(
          checker.getPropertyOfType(sourceType, staticName),
        );
        const implementation = callableImplementation(property);
        if (implementation) {
          callables.push({
            callable: implementation,
            label: exportName,
            topLevel: true,
          });
        }
        const propertyDeclaration =
          property?.valueDeclaration ?? property?.declarations?.[0];
        if (property && propertyDeclaration) {
          callables.push(
            ...reachableTypeCallables(
              checker.getTypeOfSymbolAtLocation(property, propertyDeclaration),
              exportName,
              new Set(),
            ),
          );
        }
      }
    } else if (
      ts.isArrayBindingPattern(bindingPattern) &&
      ts.isArrayLiteralExpression(variableDeclaration.initializer)
    ) {
      const index = bindingPattern.elements.indexOf(declaration);
      const element = variableDeclaration.initializer.elements[index];
      if (element && !ts.isOmittedExpression(element)) {
        addExpression(
          ts.isSpreadElement(element) ? element.expression : element,
        );
      }
    }
    return callables;
  }

  function assignedExportCallables(
    symbol: ts.Symbol | null,
    sourcePath: string,
    exportName: string,
  ): ExportedCallable[] {
    const callables: ExportedCallable[] = [];
    const sourceFile = symbol?.declarations?.[0]?.getSourceFile();
    if (!symbol || !sourceFile) {
      return callables;
    }
    const assignmentOperators = new Set<ts.SyntaxKind>([
      ts.SyntaxKind.AmpersandAmpersandEqualsToken,
      ts.SyntaxKind.BarBarEqualsToken,
      ts.SyntaxKind.EqualsToken,
      ts.SyntaxKind.QuestionQuestionEqualsToken,
    ]);

    function expressionReferencesExport(
      expression: ts.Expression,
      seen = new Set<ts.Symbol>(),
    ): boolean {
      while (
        ts.isParenthesizedExpression(expression) ||
        ts.isAsExpression(expression) ||
        ts.isSatisfiesExpression(expression) ||
        ts.isNonNullExpression(expression)
      ) {
        expression = expression.expression;
      }
      const expressionSymbol = resolvedSymbol(expression);
      if (expressionSymbol === symbol) {
        return true;
      }
      if (!expressionSymbol || seen.has(expressionSymbol)) {
        return false;
      }
      seen.add(expressionSymbol);
      return (expressionSymbol.declarations ?? []).some(
        (declaration) =>
          ts.isVariableDeclaration(declaration) &&
          declaration.initializer &&
          expressionReferencesExport(declaration.initializer, seen),
      );
    }

    function assignmentTarget(
      expression: ts.Expression,
    ): { label: string; topLevel: boolean } | null {
      if (resolvedSymbol(expression) === symbol) {
        return { label: exportName, topLevel: true };
      }
      const path: string[] = [];
      while (
        ts.isPropertyAccessExpression(expression) ||
        ts.isElementAccessExpression(expression)
      ) {
        path.unshift(
          ts.isPropertyAccessExpression(expression)
            ? expression.name.text
            : ts.isStringLiteralLike(expression.argumentExpression) ||
                ts.isNumericLiteral(expression.argumentExpression)
              ? expression.argumentExpression.text
              : "[computed]",
        );
        expression = expression.expression;
      }
      if (path.length === 0 || !expressionReferencesExport(expression)) {
        return null;
      }
      return {
        label: exportName + "." + path.join("."),
        topLevel: false,
      };
    }

    function isGlobalInstallerOwner(
      identifier: ts.Identifier,
      expectedName: "Object" | "Reflect",
    ): boolean {
      if (identifier.text !== expectedName) {
        return false;
      }
      const ownerSymbol = resolvedSymbol(identifier);
      return (
        ownerSymbol?.declarations?.some((declaration) => {
          const declarationFile = declaration.getSourceFile().fileName;
          return (
            declarationFile.includes("/typescript/lib/lib.") ||
            declarationFile.includes("/typescript/lib/lib_")
          );
        }) ?? false
      );
    }

    function installedValues(
      node: ts.CallExpression,
    ): { target: ts.Expression; values: ts.Expression[] } | null {
      if (
        !ts.isPropertyAccessExpression(node.expression) ||
        !ts.isIdentifier(node.expression.expression) ||
        !node.arguments[0]
      ) {
        return null;
      }
      const owner = node.expression.expression;
      const method = node.expression.name.text;
      if (isGlobalInstallerOwner(owner, "Object")) {
        if (method === "assign") {
          return { target: node.arguments[0], values: node.arguments.slice(1) };
        }
        if (method === "defineProperty" && node.arguments[2]) {
          return { target: node.arguments[0], values: [node.arguments[2]] };
        }
        if (
          ["defineProperties", "setPrototypeOf"].includes(method) &&
          node.arguments[1]
        ) {
          return { target: node.arguments[0], values: [node.arguments[1]] };
        }
      }
      if (
        isGlobalInstallerOwner(owner, "Reflect") &&
        method === "defineProperty" &&
        node.arguments[2]
      ) {
        return { target: node.arguments[0], values: [node.arguments[2]] };
      }
      return null;
    }

    function visit(node: ts.Node): void {
      if (
        ts.isBinaryExpression(node) &&
        assignmentOperators.has(node.operatorToken.kind)
      ) {
        const target = assignmentTarget(node.left);
        if (target) {
          const implementation =
            ts.isArrowFunction(node.right) ||
            ts.isFunctionExpression(node.right)
              ? node.right
              : callableImplementation(resolvedSymbol(node.right));
          if (implementation) {
            callables.push({
              callable: implementation,
              label: target.label,
              topLevel: target.topLevel,
            });
          }
          callables.push(...typedValueCallables(node.right, target.label));
          if (ts.isCallExpression(node.right)) {
            callables.push(
              ...callExpressionCallables(node.right, target.label).map(
                (callable) => ({
                  ...callable,
                  topLevel: target.topLevel,
                }),
              ),
            );
          }
        }
      }
      if (ts.isCallExpression(node)) {
        const installation = installedValues(node);
        const target = installation
          ? assignmentTarget(installation.target)
          : null;
        if (installation && target) {
          for (const value of installation.values) {
            callables.push(...typedValueCallables(value, target.label));
            if (ts.isCallExpression(value)) {
              callables.push(
                ...callExpressionCallables(value, target.label).map(
                  (callable) => ({ ...callable, topLevel: false }),
                ),
              );
            }
          }
        }
      }
      ts.forEachChild(node, visit);
    }

    if (sourceSegments(sourceFile.fileName).join("/") === sourcePath) {
      visit(sourceFile);
    }
    return callables;
  }

  function exportedCallables(
    symbol: ts.Symbol | null,
    sourcePath: string,
    exportName: string,
    seenExports = new Set<ts.Symbol>(),
  ): ExportedCallable[] {
    const callables: ExportedCallable[] = [];
    if (!symbol || seenExports.has(symbol)) {
      return callables;
    }
    seenExports.add(symbol);
    for (const declaration of symbol?.declarations ?? []) {
      if (declarationSourcePath(declaration) !== sourcePath) {
        continue;
      }
      if (
        ts.isFunctionDeclaration(declaration) ||
        ts.isFunctionExpression(declaration) ||
        ts.isMethodDeclaration(declaration)
      ) {
        callables.push({
          callable: declaration,
          label: exportName,
          topLevel: true,
        });
      } else if (
        ts.isVariableDeclaration(declaration) &&
        declaration.initializer &&
        (ts.isArrowFunction(declaration.initializer) ||
          ts.isFunctionExpression(declaration.initializer))
      ) {
        callables.push({
          callable: declaration.initializer,
          label: exportName,
          topLevel: true,
        });
      } else if (
        ts.isVariableDeclaration(declaration) &&
        declaration.initializer &&
        !ts.isObjectLiteralExpression(declaration.initializer) &&
        !ts.isClassExpression(declaration.initializer)
      ) {
        const implementation = callableImplementation(
          resolvedSymbol(declaration.initializer),
        );
        if (implementation) {
          callables.push({
            callable: implementation,
            label: exportName,
            topLevel: true,
          });
        }
        callables.push(
          ...typedValueCallables(declaration.initializer, exportName),
        );
        if (ts.isCallExpression(declaration.initializer)) {
          callables.push(
            ...callExpressionCallables(declaration.initializer, exportName),
          );
        }
      } else if (
        ts.isVariableDeclaration(declaration) &&
        declaration.initializer &&
        (ts.isObjectLiteralExpression(declaration.initializer) ||
          ts.isClassExpression(declaration.initializer))
      ) {
        callables.push(...callableMembers(declaration.initializer, exportName));
      } else if (ts.isClassDeclaration(declaration)) {
        callables.push(...callableMembers(declaration, exportName));
      } else if (ts.isBindingElement(declaration)) {
        callables.push(...destructuredExportCallables(declaration, exportName));
      } else if (ts.isModuleDeclaration(declaration)) {
        const moduleSymbol = resolvedSymbol(declaration.name);
        if (moduleSymbol) {
          for (const member of checker.getExportsOfModule(moduleSymbol)) {
            callables.push(
              ...exportedCallables(
                resolvedAliasSymbol(member),
                sourcePath,
                member.getName(),
                seenExports,
              ).map((callable) => ({
                ...callable,
                label: exportName + "." + callable.label,
                topLevel: false,
              })),
            );
          }
        }
      } else if (ts.isExportAssignment(declaration)) {
        const value = declaration.expression;
        const implementation =
          ts.isArrowFunction(value) || ts.isFunctionExpression(value)
            ? value
            : callableImplementation(resolvedSymbol(value));
        if (implementation) {
          callables.push({
            callable: implementation,
            label: exportName,
            topLevel: true,
          });
        }
        if (
          ts.isObjectLiteralExpression(value) ||
          ts.isClassExpression(value)
        ) {
          callables.push(...callableMembers(value, exportName));
        }
        callables.push(...typedValueCallables(value, exportName));
        if (ts.isCallExpression(value)) {
          callables.push(...callExpressionCallables(value, exportName));
        }
      }
    }
    callables.push(...assignedExportCallables(symbol, sourcePath, exportName));
    const returnQueue = [...callables];
    const inspectedReturns = new Set<CallableImplementation>();
    while (returnQueue.length > 0) {
      const exportedCallable = returnQueue.shift();
      if (
        !exportedCallable ||
        inspectedReturns.has(exportedCallable.callable)
      ) {
        continue;
      }
      inspectedReturns.add(exportedCallable.callable);
      const returned = returnedValueCallables(
        exportedCallable.callable,
        exportedCallable.label,
      );
      callables.push(...returned);
      returnQueue.push(...returned);
    }
    return callables;
  }

  const LEGACY_TRANSPORT_WRITE_EXPORTS = new Map<string, Set<string>>([
    ["shared/api/benchmarks.ts", new Set(["runParserBenchmark"])],
    [
      "shared/api/mcp.ts",
      new Set([
        "createMcpPrincipal",
        "revokeMcpPrincipal",
        "rotateMcpPrincipal",
      ]),
    ],
    ["shared/api/transport.ts", new Set(["requestJson"])],
  ]);

  function auditAdapterWriteExports(
    sourceFile: ts.SourceFile,
    sourcePath: string,
  ): void {
    const moduleSymbol = resolvedSymbol(sourceFile);
    const isDomainAdapter =
      sourcePath.startsWith("domains/") && sourcePath.includes("/api/");
    if (
      !moduleSymbol ||
      (!isDomainAdapter && !LEGACY_RAW_TRANSPORT_OWNERS.has(sourcePath))
    ) {
      return;
    }
    for (const exportedSymbol of checker.getExportsOfModule(moduleSymbol)) {
      const symbol = resolvedAliasSymbol(exportedSymbol);
      const exportName = exportedSymbol.getName();
      for (const exportedCallable of exportedCallables(
        symbol,
        sourcePath,
        exportName,
      )) {
        if (!callableWrites(exportedCallable.callable)) {
          continue;
        }
        if (
          LEGACY_TRANSPORT_WRITE_EXPORTS.get(sourcePath)?.has(exportName) &&
          exportedCallable.topLevel &&
          exportedCallable.label === exportName
        ) {
          continue;
        }
        if (
          !exportedCallable.topLevel ||
          !isWaveNineMutation(exportName) ||
          mutationNameForSymbol(symbol) !== exportName ||
          !WAVE_NINE_MUTATION_OWNERS[exportName].has(sourcePath)
        ) {
          violations.add(
            "Unregistered domain adapter write " +
              exportedCallable.label +
              ": " +
              sourcePath,
          );
        }
      }
    }
  }

  function moduleInitializerWrites(sourceFile: ts.SourceFile): boolean {
    let writes = false;

    function visit(node: ts.Node): void {
      if (writes || ts.isFunctionLike(node)) {
        return;
      }
      if (ts.isClassDeclaration(node) || ts.isClassExpression(node)) {
        for (const member of node.members) {
          if (ts.isClassStaticBlockDeclaration(member)) {
            visit(member);
          } else if (
            ts.isPropertyDeclaration(member) &&
            member.initializer &&
            member.modifiers?.some(
              (modifier) => modifier.kind === ts.SyntaxKind.StaticKeyword,
            )
          ) {
            visit(member.initializer);
          }
        }
        return;
      }
      if (ts.isCallExpression(node)) {
        const reference = callReference(node);
        const rawTransport = rawTransportSymbol(reference);
        const directCallable =
          ts.isArrowFunction(node.expression) ||
          ts.isFunctionExpression(node.expression)
            ? node.expression
            : callableImplementation(resolvedSymbol(reference));
        const receiver = invocationHelperReceiver(node);
        const receiverCallable = receiver
          ? callableImplementation(resolvedSymbol(receiver))
          : null;
        let xhrSend = false;
        if (
          ts.isPropertyAccessExpression(node.expression) ||
          ts.isElementAccessExpression(node.expression)
        ) {
          const methodName = ts.isPropertyAccessExpression(node.expression)
            ? node.expression.name.text
            : ts.isStringLiteralLike(node.expression.argumentExpression)
              ? node.expression.argumentExpression.text
              : null;
          xhrSend =
            methodName === "send" &&
            typeContainsGlobalDomType(
              checker.getTypeAtLocation(node.expression.expression),
              "XMLHttpRequest",
            );
        }
        writes =
          xhrSend ||
          mutationSymbol(reference) !== null ||
          (rawTransport !== null && rawCallWrites(node)) ||
          (directCallable !== null && callableWrites(directCallable)) ||
          (receiverCallable !== null && callableWrites(receiverCallable));
      } else if (ts.isNewExpression(node)) {
        writes = constructorImplementations(node.expression).some(
          (implementation) => callableWrites(implementation),
        );
      }
      ts.forEachChild(node, visit);
    }

    for (const statement of sourceFile.statements) {
      visit(statement);
    }
    return writes;
  }

  for (const file of scriptFiles) {
    const sourcePath = sourceSegments(file).join("/");
    const sourceFile = program.getSourceFile(file);
    if (!sourceFile) {
      violations.add(
        "TypeScript program omitted production source: " + sourcePath,
      );
      continue;
    }

    auditAdapterWriteExports(sourceFile, sourcePath);
    if (
      ((sourcePath.startsWith("domains/") && sourcePath.includes("/api/")) ||
        LEGACY_RAW_TRANSPORT_OWNERS.has(sourcePath)) &&
      moduleInitializerWrites(sourceFile)
    ) {
      violations.add("Module initializer performs a write: " + sourcePath);
    }

    for (const statement of sourceFile.statements) {
      if (
        !ts.isImportDeclaration(statement) ||
        statement.importClause?.isTypeOnly ||
        !ts.isStringLiteral(statement.moduleSpecifier) ||
        !statement.importClause?.namedBindings ||
        !ts.isNamespaceImport(statement.importClause.namedBindings)
      ) {
        continue;
      }
      if (moduleExposesBoundary(statement.moduleSpecifier)) {
        violations.add(
          "API namespace import bypasses owned symbols: " + sourcePath,
        );
      }
    }

    function visit(node: ts.Node): void {
      if (ts.isElementAccessExpression(node)) {
        const computedTransport = computedRawTransportAccess(node);
        if (computedTransport) {
          violations.add(
            (computedTransport === "[unresolved]"
              ? "Unresolved computed access on a raw-transport type: "
              : computedTransport + " accessed through a computed key: ") +
              sourcePath,
          );
        }
      }
      if (ts.isCallExpression(node)) {
        const reflectedName = reflectedBoundaryName(node);
        if (reflectedName) {
          violations.add(
            reflectedName +
              " retrieved through reflection outside its owned identity: " +
              sourcePath,
          );
        }
      }

      if (
        ts.isCallExpression(node) &&
        node.expression.kind === ts.SyntaxKind.ImportKeyword &&
        node.arguments.length === 1
      ) {
        const specifier = node.arguments[0];
        let exposesBoundary = false;
        let unresolved = false;
        if (ts.isStringLiteralLike(specifier)) {
          exposesBoundary = moduleExposesBoundary(specifier);
        } else if (ts.isTemplateExpression(specifier)) {
          const targets = templateImportTargets(file, specifier);
          unresolved = targets.length === 0;
          exposesBoundary = targets.some((target) => {
            const targetSource = program.getSourceFile(resolve(target));
            if (!targetSource) {
              unresolved = true;
              return false;
            }
            return moduleExposesBoundary(targetSource);
          });
        } else {
          unresolved = true;
        }
        if (exposesBoundary || unresolved) {
          violations.add(
            (unresolved
              ? "Unresolved dynamic import bypasses owned symbols: "
              : "Dynamic API namespace import bypasses owned symbols: ") +
              sourcePath,
          );
        }
      }

      const referenceNode =
        ts.isIdentifier(node) || ts.isStringLiteralLike(node) ? node : null;
      if (referenceNode && !isTypeOnlyReference(referenceNode)) {
        const mutation = mutationSymbol(referenceNode);
        if (mutation) {
          const owners = WAVE_NINE_MUTATION_OWNERS[mutation];
          if (owners.has(sourcePath)) {
            if (!isDirectOwnedReference(referenceNode, mutation)) {
              violations.add(
                mutation + " aliased inside its owned boundary: " + sourcePath,
              );
            }
          } else if (!isIdentitySpecifier(referenceNode, mutation)) {
            violations.add(
              mutation +
                " referenced outside its owned boundary: " +
                sourcePath,
            );
          }
        }

        const rawTransport = rawTransportSymbol(referenceNode);
        if (rawTransport) {
          if (ownsRawTransport(sourcePath)) {
            if (!isDirectOwnedReference(referenceNode, rawTransport)) {
              violations.add(
                rawTransport +
                  " aliased inside its transport boundary: " +
                  sourcePath,
              );
            }
          } else {
            violations.add(
              rawTransport +
                " referenced outside a domain transport boundary: " +
                sourcePath,
            );
          }
        }
      }

      ts.forEachChild(node, visit);
    }

    visit(sourceFile);
  }

  return [...violations].sort();
}

function stylesheetImports(source: string, file: string): string[] {
  const imports: string[] = [];
  const root = parseCss(source, { from: file });

  function sourceAfterFrom(value: string): string | null {
    const values = parseCssValue(value).nodes.filter(
      (node) => node.type !== "space" && node.type !== "comment",
    );
    const fromIndex = values.findIndex(
      (node) => node.type === "word" && node.value.toLowerCase() === "from",
    );
    const sourceValue = values[fromIndex + 1];
    return fromIndex !== -1 &&
      (sourceValue?.type === "string" || sourceValue?.type === "word")
      ? sourceValue.value
      : null;
  }

  root.walkAtRules("import", (rule) => {
    const firstValue = parseCssValue(rule.params).nodes.find(
      (node) => node.type !== "space" && node.type !== "comment",
    );
    if (!firstValue) return;

    if (firstValue.type === "string") {
      imports.push(firstValue.value);
      return;
    }
    if (
      firstValue.type !== "function" ||
      firstValue.value.toLowerCase() !== "url"
    ) {
      return;
    }

    const urlValue = firstValue.nodes.find(
      (node) => node.type !== "space" && node.type !== "comment",
    );
    if (urlValue?.type === "string" || urlValue?.type === "word") {
      imports.push(urlValue.value);
    }
  });
  root.walkAtRules("value", (rule) => {
    const sourceValue = sourceAfterFrom(rule.params);
    if (sourceValue) imports.push(sourceValue);
  });
  root.walkDecls(/^composes$/i, (declaration) => {
    const sourceValue = sourceAfterFrom(declaration.value);
    if (sourceValue && sourceValue.toLowerCase() !== "global") {
      imports.push(sourceValue);
    }
  });
  root.walkRules((rule) => {
    const values = parseCssValue(rule.selector).nodes;
    for (let index = 0; index < values.length - 1; index += 1) {
      const prefix = values[index];
      const importValue = values[index + 1];
      if (
        prefix.type !== "div" ||
        prefix.value !== ":" ||
        importValue.type !== "function" ||
        importValue.value.toLowerCase() !== "import"
      ) {
        continue;
      }
      const sourceValue = importValue.nodes.find(
        (node) => node.type !== "space" && node.type !== "comment",
      );
      if (sourceValue?.type === "string" || sourceValue?.type === "word") {
        imports.push(sourceValue.value);
      }
    }
  });
  return imports;
}

function sourceImportTarget(file: string, specifier: string): string | null {
  const suffixIndex = specifier.search(/[?#]/);
  const pathSpecifier =
    suffixIndex === -1 ? specifier : specifier.slice(0, suffixIndex);
  if (pathSpecifier.startsWith(".")) {
    return resolve(dirname(file), pathSpecifier);
  }
  if (pathSpecifier.startsWith("/src/")) {
    return resolve(SOURCE_ROOT, pathSpecifier.slice("/src/".length));
  }
  return null;
}

function viteGlobPatternGroups(source: string, file: string): string[][] {
  const groups: string[][] = [];
  const sourceFile = ts.createSourceFile(
    file,
    source,
    ts.ScriptTarget.Latest,
    true,
  );

  function staticPattern(node: ts.Expression): string | null {
    return ts.isStringLiteralLike(node) ? node.text : null;
  }

  function visit(node: ts.Node): void {
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      ts.isMetaProperty(node.expression.expression) &&
      node.expression.expression.keywordToken === ts.SyntaxKind.ImportKeyword &&
      node.expression.expression.name.text === "meta" &&
      (node.expression.name.text === "glob" ||
        node.expression.name.text === "globEager")
    ) {
      const argument = node.arguments[0];
      if (argument) {
        const patterns = ts.isArrayLiteralExpression(argument)
          ? argument.elements.flatMap((element) => {
              const pattern = ts.isExpression(element)
                ? staticPattern(element)
                : null;
              return pattern === null ? [] : [pattern];
            })
          : [staticPattern(argument)].filter(
              (pattern): pattern is string => pattern !== null,
            );
        if (patterns.length > 0) groups.push(patterns);
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return groups;
}

function viteStaticUrlSpecifiers(source: string, file: string): string[] {
  const specifiers: string[] = [];
  const sourceFile = ts.createSourceFile(
    file,
    source,
    ts.ScriptTarget.Latest,
    true,
  );

  function visit(node: ts.Node): void {
    if (
      ts.isNewExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === "URL" &&
      node.arguments?.length === 2 &&
      ts.isStringLiteralLike(node.arguments[0]) &&
      ts.isPropertyAccessExpression(node.arguments[1]) &&
      ts.isMetaProperty(node.arguments[1].expression) &&
      node.arguments[1].expression.keywordToken ===
        ts.SyntaxKind.ImportKeyword &&
      node.arguments[1].expression.name.text === "meta" &&
      node.arguments[1].name.text === "url"
    ) {
      specifiers.push(node.arguments[0].text);
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return specifiers;
}

function scriptImports(source: string, file: string): string[] {
  const preprocessed = ts.preProcessFile(source, true, true);
  return preprocessed.importedFiles
    .concat(preprocessed.referencedFiles)
    .concat(preprocessed.typeReferenceDirectives)
    .concat(preprocessed.libReferenceDirectives)
    .map((importedFile) => importedFile.fileName)
    .concat(viteStaticUrlSpecifiers(source, file));
}

function viteGlobImports(
  file: string,
  source: string,
): Array<{ specifier: string; target: string }> {
  const sourceRootFromImporter =
    relative(dirname(file), SOURCE_ROOT).split(sep).join("/") || ".";

  return viteGlobPatternGroups(source, file).flatMap((patterns) => {
    const resolvedPatterns = patterns.map((pattern) => {
      const negated = pattern.startsWith("!");
      const value = negated ? pattern.slice(1) : pattern;
      const resolved = value.startsWith("/src/")
        ? `${sourceRootFromImporter}/${value.slice("/src/".length)}`
        : value;
      return negated ? `!${resolved}` : resolved;
    });
    const specifier = `import.meta.glob(${JSON.stringify(patterns)})`;
    return globSync(resolvedPatterns, {
      absolute: true,
      cwd: dirname(file),
      onlyFiles: true,
    }).map((target) => ({ specifier, target }));
  });
}

function sourceImports(
  file: string,
): Array<{ specifier: string; target: string }> {
  const source = readFileSync(file, "utf8");
  const imports =
    extname(file) === ".css"
      ? stylesheetImports(source, file)
      : scriptImports(source, file);
  return imports
    .flatMap((specifier) => {
      const target = sourceImportTarget(file, specifier);
      return target ? [{ specifier, target }] : [];
    })
    .concat(viteGlobImports(file, source));
}

function resolvedSourceFile(target: string, importer: string): string {
  if (existsSync(target)) return target;
  const extensions =
    extname(importer) === ".css"
      ? [".css", ".scss", ".sass"]
      : [".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"];
  for (const extension of extensions) {
    const candidate = `${target}${extension}`;
    if (existsSync(candidate)) return candidate;
  }
  for (const extension of extensions) {
    const candidate = join(target, `index${extension}`);
    if (existsSync(candidate)) return candidate;
  }
  return target;
}

function peerFeatureEdges(): Set<string> {
  const edges = new Set<string>();
  for (const file of sourceFiles()) {
    const sourcePath = sourceSegments(file);
    if (sourcePath[0] !== "features") continue;
    for (const { target } of sourceImports(file)) {
      const targetPath = sourceSegments(resolvedSourceFile(target, file));
      if (targetPath[0] === "features" && sourcePath[1] !== targetPath[1]) {
        edges.add(`${sourcePath.join("/")} -> ${targetPath.join("/")}`);
      }
    }
  }
  return edges;
}

function peerFeatureBoundaryViolations(): string[] {
  const current = peerFeatureEdges();
  const baselineShape = [...new Set(PEER_FEATURE_BASELINE_ENTRIES)].sort();
  return [
    ...(JSON.stringify(PEER_FEATURE_BASELINE_ENTRIES) !==
    JSON.stringify(baselineShape)
      ? ["peer-feature baseline must be sorted and duplicate-free"]
      : []),
    ...[...current]
      .filter((edge) => !PEER_FEATURE_BASELINE.has(edge))
      .sort()
      .map((edge) => `new peer-feature import: ${edge}`),
    ...[...PEER_FEATURE_BASELINE]
      .filter((edge) => !current.has(edge))
      .sort()
      .map((edge) => `stale peer-feature baseline entry: ${edge}`),
  ];
}

function layerViolations(): string[] {
  const violations: string[] = [];

  for (const file of sourceFiles()) {
    const sourcePath = sourceSegments(file);
    if (JAVASCRIPT_EXTENSIONS.has(extname(file))) {
      violations.push(
        `production source must use TypeScript instead of JavaScript: ${sourcePath.join("/")}`,
      );
      continue;
    }
    const currentSourceLayer = sourceLayer(sourcePath);
    if (!currentSourceLayer) {
      violations.push(
        `production source must live in a declared layer: ${sourcePath.join("/")}`,
      );
      continue;
    }
    const featurePlacementError = ["workflows", "features", "domains"].includes(
      currentSourceLayer,
    )
      ? featurePlacementViolation(sourcePath)
      : null;
    if (featurePlacementError) {
      violations.push(`${featurePlacementError}: ${sourcePath.join("/")}`);
      continue;
    }

    for (const { specifier, target } of sourceImports(file)) {
      const targetPath = sourceSegments(target);
      const targetLayer = sourceLayer(targetPath) ?? targetPath[0];
      const importDescription = `${sourcePath.join("/")} -> ${specifier}`;

      if (isTestSupportPath(targetPath)) {
        violations.push(
          `production source may not depend on test support: ${importDescription}`,
        );
        continue;
      }

      if (
        isGeneratedOpenApiPath(targetPath) &&
        !generatedOpenApiImportAllowed(sourcePath)
      ) {
        violations.push(
          `generated OpenAPI contracts may only be imported by shared API transport or compatibility modules and domain API adapters: ${importDescription}`,
        );
      }

      const allowedTargets = ALLOWED_LAYER_IMPORTS[currentSourceLayer];
      if (
        !allowedTargets.has(targetLayer) &&
        !domainCompatibilityFacadeImportAllowed(sourcePath, targetPath)
      ) {
        violations.push(
          `${currentSourceLayer} may not depend on ${targetLayer}: ${importDescription}`,
        );
        continue;
      }

      if (currentSourceLayer !== "features" || targetLayer !== "features") {
        const sourceKind = featureArea(sourcePath);
        if (
          sourceKind !== null &&
          NON_COMPONENT_FEATURE_AREAS.has(sourceKind) &&
          featureArea(targetPath) === "components"
        ) {
          violations.push(
            `${sourcePath[0]} ${sourceKind} may not depend on components: ${importDescription}`,
          );
        }
        continue;
      }

      const sourceKind = sourcePath[2];
      const targetKind = targetPath[2];
      if (sourceKind === "lib" && targetKind === "hooks") {
        violations.push(
          `feature lib may not depend on hooks: ${importDescription}`,
        );
      }
      if (
        NON_COMPONENT_FEATURE_AREAS.has(sourceKind ?? "") &&
        targetKind === "components"
      ) {
        violations.push(
          `feature ${sourceKind} may not depend on components: ${importDescription}`,
        );
      }
    }
  }

  return violations;
}

function componentsMissingTests(): string[] {
  return sourceFiles()
    .filter((file) => sourceSegments(file).includes("components"))
    .filter((file) => extname(file) === ".tsx")
    .filter((file) => !existsSync(file.replace(/\.tsx$/, ".test.tsx")))
    .map((file) => sourceSegments(file).join("/"));
}

function sharedTypeBoundaryViolations(): string[] {
  const violations: string[] = [];
  const barrel = resolve(SOURCE_ROOT, "shared/types.ts");
  const barrelTargets = new Set([
    barrel,
    barrel.slice(0, -extname(barrel).length),
  ]);
  const sourceFile = ts.createSourceFile(
    barrel,
    readFileSync(barrel, "utf8"),
    ts.ScriptTarget.Latest,
    true,
  );
  const exportedModules = new Set<string>();

  if (sourceFile.statements.length === 0) {
    violations.push("shared/types.ts must export domain type modules");
  }

  for (const statement of sourceFile.statements) {
    if (
      !ts.isExportDeclaration(statement) ||
      !statement.isTypeOnly ||
      statement.exportClause !== undefined ||
      !statement.moduleSpecifier ||
      !ts.isStringLiteralLike(statement.moduleSpecifier) ||
      !statement.moduleSpecifier.text.startsWith("./types/")
    ) {
      violations.push(
        "shared/types.ts must contain only domain `export type *` declarations",
      );
      continue;
    }

    if (exportedModules.has(statement.moduleSpecifier.text)) {
      violations.push(
        `shared type barrel target is exported more than once: ${statement.moduleSpecifier.text}`,
      );
    }
    exportedModules.add(statement.moduleSpecifier.text);
    const target = resolve(
      dirname(barrel),
      `${statement.moduleSpecifier.text}.ts`,
    );
    if (!existsSync(target)) {
      violations.push(
        `shared type barrel target does not exist: ${statement.moduleSpecifier.text}`,
      );
    }
  }

  function importsTypeBarrel(file: string): boolean {
    return scriptImports(readFileSync(file, "utf8"), file).some((specifier) => {
      const target = sourceImportTarget(file, specifier);
      return target !== null && barrelTargets.has(target);
    });
  }

  const apiRoot = resolve(SOURCE_ROOT, "shared/api");
  for (const file of filesBelow(apiRoot).filter(
    (candidate) =>
      extname(candidate) === ".ts" &&
      !isTestSupportPath(sourceSegments(candidate)),
  )) {
    const sourcePath = sourceSegments(file);
    if (
      ["client.ts", "core.ts"].includes(sourcePath[sourcePath.length - 1] ?? "")
    ) {
      continue;
    }
    if (importsTypeBarrel(file)) {
      violations.push(
        `shared API domains must import their owning type modules directly: ${sourcePath.join("/")}`,
      );
    }
  }

  const typeRoot = resolve(SOURCE_ROOT, "shared/types");
  for (const file of filesBelow(typeRoot).filter(
    (candidate) => extname(candidate) === ".ts",
  )) {
    if (importsTypeBarrel(file)) {
      violations.push(
        `shared type domains may not import their compatibility barrel: ${sourceSegments(file).join("/")}`,
      );
    }
  }

  return violations;
}

interface FeatureLibraryBarrelBoundary {
  barrelPath: string;
  label: string;
  namedExportsAllowed: boolean;
}

function featureLibraryBarrelViolations({
  barrelPath,
  label,
  namedExportsAllowed,
}: FeatureLibraryBarrelBoundary): string[] {
  const violations: string[] = [];
  const barrel = resolve(SOURCE_ROOT, barrelPath);
  const barrelTargets = new Set([
    barrel,
    barrel.slice(0, -extname(barrel).length),
  ]);
  const sourceFile = ts.createSourceFile(
    barrel,
    readFileSync(barrel, "utf8"),
    ts.ScriptTarget.Latest,
    true,
  );
  const exportedModules = new Set<string>();

  if (sourceFile.statements.length === 0) {
    violations.push(`${label} must export focused modules`);
  }

  for (const statement of sourceFile.statements) {
    if (
      !ts.isExportDeclaration(statement) ||
      (!namedExportsAllowed && statement.exportClause !== undefined) ||
      !statement.moduleSpecifier ||
      !ts.isStringLiteralLike(statement.moduleSpecifier) ||
      !statement.moduleSpecifier.text.startsWith("./")
    ) {
      violations.push(`${label} barrel must contain only module re-exports`);
      continue;
    }

    const moduleSpecifier = statement.moduleSpecifier.text;
    if (exportedModules.has(moduleSpecifier)) {
      violations.push(
        `${label} module is exported more than once: ${moduleSpecifier}`,
      );
    }
    exportedModules.add(moduleSpecifier);
    const target = resolve(dirname(barrel), `${moduleSpecifier}.ts`);
    if (target === barrel) {
      violations.push(`${label} barrel may not re-export itself`);
    } else if (!existsSync(target)) {
      violations.push(
        `${label} barrel target does not exist: ${moduleSpecifier}`,
      );
    }
  }

  for (const file of filesBelow(dirname(barrel)).filter(
    (candidate) =>
      candidate !== barrel &&
      extname(candidate) === ".ts" &&
      !isTestSupportPath(sourceSegments(candidate)),
  )) {
    const importsBarrel = scriptImports(readFileSync(file, "utf8"), file).some(
      (specifier) => {
        const importTarget = sourceImportTarget(file, specifier);
        return importTarget !== null && barrelTargets.has(importTarget);
      },
    );
    if (importsBarrel) {
      violations.push(
        `${label} libraries may not import their compatibility barrel: ${sourceSegments(file).join("/")}`,
      );
    }
  }

  return violations;
}

function workspacePersistenceBoundaryViolations(): string[] {
  return featureLibraryBarrelViolations({
    barrelPath: "features/workspace/lib/persistence.ts",
    label: "workspace persistence",
    namedExportsAllowed: false,
  });
}

function cacheValidationBoundaryViolations(): string[] {
  return featureLibraryBarrelViolations({
    barrelPath: "features/workspace/lib/cacheValidation.ts",
    label: "workspace cache validation",
    namedExportsAllowed: true,
  });
}

function mutationLeaseBoundaryViolations(): string[] {
  return featureLibraryBarrelViolations({
    barrelPath: "features/workspace/lib/mutationLeases.ts",
    label: "workspace mutation leases",
    namedExportsAllowed: true,
  });
}

function recommendationPresentationBoundaryViolations(): string[] {
  return featureLibraryBarrelViolations({
    barrelPath: "features/recommendation/lib/recommendationPresentation.ts",
    label: "recommendation presentation",
    namedExportsAllowed: true,
  });
}

function postflopEvidenceBoundaryViolations(): string[] {
  return featureLibraryBarrelViolations({
    barrelPath: "features/recommendation/lib/postflopEvidencePresentation.ts",
    label: "postflop evidence presentation",
    namedExportsAllowed: true,
  });
}

function preflopEvidenceBoundaryViolations(): string[] {
  return featureLibraryBarrelViolations({
    barrelPath: "features/recommendation/lib/preflopEvidencePresentation.ts",
    label: "preflop evidence presentation",
    namedExportsAllowed: true,
  });
}

function trainingPresentationBoundaryViolations(): string[] {
  return featureLibraryBarrelViolations({
    barrelPath: "features/training/lib/trainingPresentation.ts",
    label: "training presentation",
    namedExportsAllowed: true,
  });
}

function handReviewPokerStateBoundaryViolations(): string[] {
  return featureLibraryBarrelViolations({
    barrelPath: "features/hand-review/lib/pokerState.ts",
    label: "hand-review poker state",
    namedExportsAllowed: true,
  });
}

function benchmarkPresentationBoundaryViolations(): string[] {
  return featureLibraryBarrelViolations({
    barrelPath: "features/benchmark/lib/benchmarkPresentation.ts",
    label: "benchmark presentation",
    namedExportsAllowed: true,
  });
}

describe("frontend source architecture", () => {
  it("recognizes only declared layers and the bootstrap entry point", () => {
    expect(sourceLayer(["main.tsx"])).toBe("bootstrap");
    expect(
      sourceLayer(["features", "capture", "lib", "captureSource.ts"]),
    ).toBe("features");
    expect(sourceLayer(["workflows", "capture", "lib", "capture.ts"])).toBe(
      "workflows",
    );
    expect(sourceLayer(["domains", "cards", "model", "card.ts"])).toBe(
      "domains",
    );
    expect(sourceLayer(["utils", "format.ts"])).toBeNull();
  });

  it("recognizes only declared production areas inside features", () => {
    expect(
      featureArea(["features", "capture", "lib", "captureSource.ts"]),
    ).toBe("lib");
    expect(featureArea(["features", "capture", "index.ts"])).toBeNull();
    expect(featureArea(["workflows", "analyzer", "store", "state.ts"])).toBe(
      "store",
    );
    expect(featureArea(["features", "capture", "services", "api.ts"])).toBe(
      "services",
    );
    expect(featureArea(["domains", "cards", "model", "card.ts"])).toBe("model");
    expect(
      featureArea(["features", "capture", "utils", "format.ts"]),
    ).toBeNull();
  });

  it("limits domain compatibility imports to declared API facades", () => {
    expect(
      domainCompatibilityFacadeImportAllowed(
        ["shared", "api", "jobs.ts"],
        ["domains", "jobs", "api", "jobsApi.ts"],
      ),
    ).toBe(true);
    expect(
      domainCompatibilityFacadeImportAllowed(
        ["shared", "api", "benchmarks.ts"],
        ["domains", "benchmarks", "api", "benchmarksApi.ts"],
      ),
    ).toBe(true);
    expect(
      domainCompatibilityFacadeImportAllowed(
        ["shared", "api", "training.ts"],
        ["domains", "training", "api", "trainingApi.ts"],
      ),
    ).toBe(true);
    expect(
      domainCompatibilityFacadeImportAllowed(
        ["shared", "api", "history.ts"],
        ["domains", "history", "api", "historyApi.ts"],
      ),
    ).toBe(true);
    expect(
      domainCompatibilityFacadeImportAllowed(
        ["shared", "api", "client.ts"],
        ["domains", "jobs", "api", "jobsApi.ts"],
      ),
    ).toBe(false);
  });

  it("includes Vite JavaScript modules in the TypeScript-only source audit", () => {
    for (const extension of [".cjs", ".js", ".jsx", ".mjs"]) {
      expect(SOURCE_EXTENSIONS.has(extension)).toBe(true);
      expect(JAVASCRIPT_EXTENSIONS.has(extension)).toBe(true);
    }
    for (const extension of [".cts", ".mts"]) {
      expect(SOURCE_EXTENSIONS.has(extension)).toBe(true);
      expect(JAVASCRIPT_EXTENSIONS.has(extension)).toBe(false);
    }
  });

  it("keeps feature UI source in component areas", () => {
    expect(
      featurePlacementViolation([
        "features",
        "capture",
        "components",
        "InputSourcePanel.tsx",
      ]),
    ).toBeNull();
    expect(
      featurePlacementViolation([
        "features",
        "capture",
        "lib",
        "CaptureWidget.tsx",
      ]),
    ).toContain("TSX");
    expect(
      featurePlacementViolation([
        "features",
        "capture",
        "hooks",
        "captureWidget.css",
      ]),
    ).toContain("CSS");
  });

  it("recognizes test support wherever it is stored", () => {
    expect(
      isTestSupportPath([
        "features",
        "capture",
        "lib",
        "captureSource.test.ts",
      ]),
    ).toBe(true);
    expect(isTestSupportPath(["pages", "analyzer", "__tests__"])).toBe(true);
    expect(isTestSupportPath(["test", "analyzerHarness.tsx"])).toBe(true);
    expect(
      isTestSupportPath(["features", "capture", "lib", "captureSource.test"]),
    ).toBe(true);
    expect(
      isTestSupportPath(["features", "capture", "lib", "captureSource.ts"]),
    ).toBe(false);
  });

  it("parses source stylesheet imports without treating URLs as source edges", () => {
    expect(
      stylesheetImports(
        '@import "../../../pages/analyzer/AnalyzerPage.css";\n@import url("./local.css");\n@import "/src/shared/styles/base.css";\n@import url("https://example.com/font.css");\n@value brand from "./tokens.module.css";\n.button { composes: card from "../../../pages/analyzer/Page.module.css"; }\n.global { composes: shadow from global; }\n:import("/src/shared/styles/tokens.css") { token: color; }',
        "fixture.css",
      ).filter(
        (specifier) => sourceImportTarget("fixture.css", specifier) !== null,
      ),
    ).toEqual([
      "../../../pages/analyzer/AnalyzerPage.css",
      "./local.css",
      "/src/shared/styles/base.css",
      "./tokens.module.css",
      "../../../pages/analyzer/Page.module.css",
      "/src/shared/styles/tokens.css",
    ]);
  });

  it("resolves relative and Vite root-relative source imports", () => {
    const importer = resolve(SOURCE_ROOT, "shared/styles/base.css");
    expect(sourceImportTarget(importer, "./tokens.css")).toBe(
      resolve(SOURCE_ROOT, "shared/styles/tokens.css"),
    );
    expect(
      sourceImportTarget(importer, "/src/pages/analyzer/AnalyzerPage.css"),
    ).toBe(resolve(SOURCE_ROOT, "pages/analyzer/AnalyzerPage.css"));
    expect(
      sourceImportTarget(importer, "https://example.com/font.css"),
    ).toBeNull();
  });

  it("removes Vite query and hash suffixes before classifying imports", () => {
    const importer = resolve(SOURCE_ROOT, "features/capture/lib/consumer.ts");
    for (const specifier of [
      "./captureSource.test?raw",
      "./captureSource.test#fixture",
    ]) {
      const target = sourceImportTarget(importer, specifier);
      expect(target).not.toBeNull();
      expect(isTestSupportPath(sourceSegments(target!))).toBe(true);
    }
    expect(
      sourceImportTarget(importer, "/src/shared/styles/base.css?inline"),
    ).toBe(resolve(SOURCE_ROOT, "shared/styles/base.css"));
  });

  it("extracts static Vite glob patterns", () => {
    expect(
      viteGlobPatternGroups(
        'const pages = import.meta.glob(["../../pages/**/*.tsx", "!../../pages/**/*.test.tsx"]);\nconst styles = import.meta.globEager(`/src/shared/**/*.css`);',
        "fixture.ts",
      ),
    ).toEqual([
      ["../../pages/**/*.tsx", "!../../pages/**/*.test.tsx"],
      ["/src/shared/**/*.css"],
    ]);
  });

  it("extracts Vite static URL dependencies", () => {
    expect(
      viteStaticUrlSpecifiers(
        'const worker = new Worker(new URL("../../pages/worker.ts", import.meta.url));\nconst external = new URL(value, baseUrl);',
        "fixture.ts",
      ),
    ).toEqual(["../../pages/worker.ts"]);
  });

  it("includes triple-slash references as source imports", () => {
    const imports = scriptImports(
      '/// <reference path="../../pages/analyzer/types.d.ts" />\n/// <reference types="../../pages/analyzer/types" />',
      "fixture.ts",
    );
    expect(imports).toContain("../../pages/analyzer/types.d.ts");
    expect(imports).toContain("../../pages/analyzer/types");
  });

  it("expands Vite glob imports into auditable source targets", () => {
    const importer = resolve(SOURCE_ROOT, "shared/lib/registry.ts");
    const imports = viteGlobImports(
      importer,
      'const pages = import.meta.glob(["../../pages/**/*.tsx", "!../../pages/**/__tests__/**"]);',
    );
    expect(
      imports.some((entry) =>
        entry.target.endsWith("/pages/analyzer/AnalyzerPage.tsx"),
      ),
    ).toBe(true);
    expect(imports.some((entry) => entry.target.includes("/__tests__/"))).toBe(
      false,
    );
  });

  it("keeps imports within the documented layer direction", () => {
    expect(layerViolations()).toEqual([]);
  });

  it("keeps Wave 9 mutations in owned adapters and command services", () => {
    expect(waveNineMutationBoundaryViolations()).toEqual([]);
  });

  it("allows only the checked-in legacy peer-feature imports", () => {
    expect(peerFeatureBoundaryViolations()).toEqual([]);
  });

  it("keeps tests colocated with production components", () => {
    expect(componentsMissingTests()).toEqual([]);
  });

  it("keeps shared API contracts in domain type modules", () => {
    expect(sharedTypeBoundaryViolations()).toEqual([]);
  });

  it("keeps workspace persistence in focused modules", () => {
    expect(workspacePersistenceBoundaryViolations()).toEqual([]);
  });

  it("keeps workspace cache validation in focused modules", () => {
    expect(cacheValidationBoundaryViolations()).toEqual([]);
  });

  it("keeps workspace mutation leases in focused modules", () => {
    expect(mutationLeaseBoundaryViolations()).toEqual([]);
  });

  it("keeps recommendation presentation in focused modules", () => {
    expect(recommendationPresentationBoundaryViolations()).toEqual([]);
  });

  it("keeps postflop evidence presentation in focused modules", () => {
    expect(postflopEvidenceBoundaryViolations()).toEqual([]);
  });

  it("keeps preflop evidence presentation in focused modules", () => {
    expect(preflopEvidenceBoundaryViolations()).toEqual([]);
  });

  it("keeps training presentation in focused modules", () => {
    expect(trainingPresentationBoundaryViolations()).toEqual([]);
  });

  it("keeps hand-review poker state in focused modules", () => {
    expect(handReviewPokerStateBoundaryViolations()).toEqual([]);
  });

  it("keeps benchmark presentation in focused modules", () => {
    expect(benchmarkPresentationBoundaryViolations()).toEqual([]);
  });
});
