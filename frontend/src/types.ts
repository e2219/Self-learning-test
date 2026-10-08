export type Course = {
  id: string;
  name: string;
  description: string;
  document_count: number;
  exam_count: number;
  wrong_count: number;
};
export type Document = {
  id: string;
  name: string;
  kind: string;
  page_count: number;
  usable_pages: number;
  ocr_pages: number;
  warnings: string[];
  outline: { title: string; page: number; depth: number }[];
};
export type Page = {
  number: number;
  text: string;
  warning: string;
  edited: number;
  has_table: boolean;
  needs_review: boolean;
  table_issues: string[];
  text_hash: string;
};
export type QuestionType = 'choice' | 'true_false' | 'fill' | 'calculation' | 'proof';
export const typeNames: Record<QuestionType, string> = {
  choice: '选择题',
  true_false: '判断题',
  fill: '填空题',
  calculation: '计算题',
  proof: '证明题',
};
export type Source = { document_id: string; page: number; name: string };
export type Question = {
  id: string;
  exam_id: string;
  position: number;
  type: QuestionType;
  points: number;
  status: string;
  stem: string;
  blanks?: { answer: string; alternatives: string[] }[];
  review?: { status?: string };
  options: string[];
  answer: string;
  explanation: string;
  rubric: string[];
  knowledge: string;
  sources: Source[];
  error: string;
  user_answer: string;
  self_score: number | null;
  is_wrong: number;
  is_favorite: number;
  course_name?: string;
  exam_title?: string;
};
export type SourceRange = { document_id: string; start: number; end: number };
export type ExamConfig = {
  imported?: boolean;
  course_id: string;
  title: string;
  ranges: SourceRange[];
  rules: { type: QuestionType; count: number; points: number }[];
  mode: string;
  random_count: number;
  difficulty: string;
  focus: string;
  duration: number;
  style?: string;
  submission_id?: string;
  parent_plan_id?: string;
  plan_id?: string;
  blueprint?: PlanSlot[];
};
export type Exam = {
  id: string;
  title: string;
  course_id: string;
  course_name: string;
  status: string;
  error: string;
  tokens: number;
  created_at: string;
  total_points: number;
  question_count?: number;
  ready_count?: number;
  config: ExamConfig;
  coverage?: { title: string; planned: number; completed: number }[];
  planning_tokens?: number;
  questions: Question[];
};
export type Settings = {
  has_key: boolean;
  key_from_env: boolean;
  model: string;
  ocr_model: string;
  ocr_max_pages: number;
  max_pdf_bytes: number;
  max_pdf_pages: number;
};

export type PlanSlot = { topic_id: string; type: QuestionType; points: number; objective: string };
export type ExamPlan = {
  config: ExamConfig;
  basis_config: ExamConfig;
  revision: number;
  updated_at: string;
  needs_replan: boolean;
  source_changes: { key: string; label: string }[];
  parent_id?: string;
  exam_id?: string;
  cache_hits: number;
  id: string;
  status: string;
  error: string;
  tokens: number;
  topics: {
    id: string;
    title: string;
    objective: string;
    reasons: string[];
    sources: { name: string; page: number; quote: string }[];
  }[];
  blueprint: PlanSlot[];
  excluded: { name: string; page: number; reason: string }[];
};
