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
  text_source?: 'manual' | 'ocr' | 'pdf';
  text_quality_issue?: string;
  number: number;
  text: string;
  warning: string;
  edited: number;
  has_table: boolean;
  needs_review: boolean;
  auto_usable?: boolean;
  table_issues: string[];
  text_hash: string;
};
export type QuestionType =
  | 'choice'
  | 'multiple_choice'
  | 'indefinite_choice'
  | 'true_false'
  | 'fill'
  | 'calculation'
  | 'proof';
export const typeNames: Record<QuestionType, string> = {
  choice: '单选题',
  multiple_choice: '多选题',
  indefinite_choice: '不定项选择题',
  true_false: '判断题',
  fill: '填空题',
  calculation: '计算题',
  proof: '证明题',
};
export type Source = {
  document_id: string;
  page: number;
  name: string;
  imported?: boolean;
  modified?: boolean;
  url?: string;
  authors_url?: string;
  license?: string;
  license_url?: string;
  revision?: number;
};
export type Question = {
  course_id?: string;
  practice_source_id?: string | null;
  practice_exam_id?: string;
  id: string;
  exam_id: string;
  position: number;
  type: QuestionType;
  points: number;
  status: string;
  stem: string;
  blanks?: { answer: string; alternatives: string[] }[];
  review?: {
    status?: string;
    method?: string;
    source_images_checked?: boolean;
    expanded_explanation?: boolean;
    local_checks?: {
      arithmetic: number;
      logic: number;
      numeric_options: number;
      skipped: number;
      scope: string;
    };
  };
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
export type SourceRange = {
  role?: 'auto' | 'knowledge' | 'reference';
  document_id: string;
  start: number;
  end: number;
};
export type ExamConfig = {
  practice?: boolean;
  origin?: string;
  course_id: string;
  title: string;
  ranges: SourceRange[];
  rules: { type: QuestionType; count: number; points: number }[];
  reading_mode?: 'study' | 'vision';
  review_mode?: 'full' | 'adaptive';
  mode: string;
  random_count: number;
  difficulty: string;
  focus: string;
  instructions?: string;
  max_attempts?: number;
  token_budget?: number;
  batch_generation?: boolean;
  answer_detail?: 'concise' | 'full';
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
  usage?: import('./Usage').UsageRow[];
  questions: Question[];
};
export type Settings = {
  deepseek_has_key: boolean;
  has_vision_key: boolean;
  providers: Record<'text' | 'vision', import('./ProviderSettings').Provider>;
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
  usage?: import('./Usage').UsageRow[];
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
    reference_structure?: {
      question_type: QuestionType | null;
      occurrences: number;
      original_points: number | null;
      difficulty: string | null;
      question_style: string;
      key_conditions: string[];
    }[];
    sources: { name: string; page: number; quote: string }[];
  }[];
  blueprint: PlanSlot[];
  excluded: { name: string; page: number; reason: string }[];
};

export const isChoice = (type: QuestionType) =>
  ['choice', 'multiple_choice', 'indefinite_choice'].includes(type);
export const isMultiChoice = (type: QuestionType) =>
  ['multiple_choice', 'indefinite_choice'].includes(type);
export function toggleChoice(answer: string, option: string) {
  const selected = new Set(answer.match(/[A-D]/gi)?.map((s) => s.toUpperCase()) || []);
  if (selected.has(option)) selected.delete(option);
  else selected.add(option);
  return [...selected].sort().join('');
}
