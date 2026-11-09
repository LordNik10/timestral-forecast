export type ColumnType = "datetime" | "season" | "year" | "integer" | "float" | "boolean" | "text" | "empty";
export type Aggregation = "sum" | "mean";
export type JobStatus = "queued" | "running" | "done" | "error";

export interface ColumnInfo {
  name: string;
  type: ColumnType;
  n_missing: number;
  n_unique: number;
}

export interface GroupValue {
  value: string;
  count: number;
}

export interface InspectResponse {
  file_id: string;
  file_name: string;
  n_rows: number;
  columns: ColumnInfo[];
  preview: Record<string, string | number | boolean | null>[];
  suggested_time_col: string | null;
  suggested_value_col: string | null;
  suggested_group_col: string | null;
  detected_frequency: string | null;
  suggested_horizon: number;
  group_col: string | null;
  group_values: GroupValue[] | null;
}

export interface ModelInfo {
  name: string;
  size: string;
  repo: string;
  weight_mb: number;
  cached: boolean;
  loaded: boolean;
  default: boolean;
}

export interface ModelsResponse {
  device: string;
  models: ModelInfo[];
}

export interface ForecastRequest {
  file_id: string;
  time_col: string;
  value_col: string;
  group_col: string | null;
  group_value: string | null;
  aggregation: Aggregation;
  models: string[];
  horizon: number;
  backtest_windows: number;
}

export interface JobResponse {
  status: JobStatus;
  stage: string;
  progress: number;
  message: string | null;
  result?: ForecastResult;
}

export type Num = number | null;

export interface BacktestRow {
  origin: string;
  t: string;
  step: number;
  y: Num;
  p10: Num;
  p50: Num;
  p90: Num;
  [baseline: string]: string | number | null;
}

export interface ForecastRow {
  t: string;
  p10: Num;
  p50: Num;
  p90: Num;
  quantiles: Num[];
}

export interface PointMetrics {
  mae: Num;
  rmse: Num;
  smape: Num;
  mase: Num;
}

export interface ModelMetrics extends PointMetrics {
  coverage_80: Num;
  width_80: Num;
  wql: Num;
}

export interface ModelResult {
  backtest: BacktestRow[];
  metrics: { model: ModelMetrics } & Record<string, PointMetrics>;
  forecast: ForecastRow[];
  summary: string;
}

export interface ResultMeta {
  time_col: string;
  value_col: string;
  group_col: string | null;
  group: string | null;
  aggregation: Aggregation;
  frequency: string;
  frequency_label: string;
  time_kind: string;
  season_length: number | null;
  n_obs: number;
  n_missing: number;
  horizon: number;
  backtest_horizon: number;
  backtest_windows: number;
  requested_windows: number;
  mean_k: number;
  file_name: string | null;
  warnings: string[];
  quantile_levels: number[];
  device: string;
}

export interface ForecastResult {
  meta: ResultMeta;
  history: { t: string; y: Num }[];
  baselines: string[];
  baseline_labels: Record<string, string>;
  models: Record<string, ModelResult>;
}

/** Il file JSON salvato dall'utente: basta per ridisegnare la dashboard senza backend. */
export interface SavedSession {
  app: "timestral-forecast";
  version: 1;
  saved_at: string;
  file_name: string;
  request: ForecastRequest;
  group_values: GroupValue[] | null;
  result: ForecastResult;
}
