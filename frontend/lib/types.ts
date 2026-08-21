export type Role = "CUSTOMER" | "AGENT" | "ADMIN";

export type ClaimStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "PROCESSING"
  | "AI_ANALYZING"
  | "MARKET_RESEARCH"
  | "ESTIMATING"
  | "AI_COMPLETED"
  | "AGENT_REVIEW"
  | "MORE_INFORMATION_REQUIRED"
  | "APPROVED"
  | "REJECTED"
  | "SETTLEMENT_PROCESSING"
  | "COMPLETED";

export type MoneyRange = {
  status: "AVAILABLE" | "UNAVAILABLE";
  min: number | null;
  max: number | null;
  median?: number | null;
  currency: string | null;
  confidence: number | null;
  reason?: string | null;
  manual_verification_required: boolean;
  source_count: number;
};

export type User = {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  role: Role;
  is_active: boolean;
  created_at: string;
};

export type MeResponse = {
  user: User;
  customer: { id: string; city: string | null; country: string } | null;
  agent: { id: string; employee_code: string; branch: string | null } | null;
};

export type Vehicle = {
  id: string;
  registration_number: string | null;
  make: string | null;
  model: string | null;
  variant: string | null;
  year: number | null;
  vehicle_type: string | null;
  color: string | null;
  is_primary: boolean;
  display_name: string;
};

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

export type ClaimSummary = {
  id: string;
  claim_number: string;
  status: ClaimStatus;
  priority: string;
  vehicle_label: string | null;
  customer_name: string | null;
  image_count: number;
  damaged_part_count: number;
  estimate: MoneyRange | null;
  location_label: string | null;
  location_latitude: number | null;
  location_longitude: number | null;
  location_source: string | null;
  thumbnail_url: string | null;
  accident_datetime: string | null;
  photo_captured_at: string | null;
  assigned_agent_name: string | null;
  manual_review_required: boolean;
  overall_confidence: number | null;
  created_at: string;
  submitted_at: string | null;
};

export type AppNotification = {
  id: string;
  claim_id: string | null;
  notification_type: string;
  title: string;
  body: string;
  payload: Record<string, unknown>;
  is_read: boolean;
  created_at: string;
};

export type ClaimImage = {
  id: string;
  image_role: string;
  url: string | null;
  annotated_url: string | null;
  customer_note: string | null;
  quality_score: number | null;
  validation_status: string;
  validation_errors: string[];
  image_metadata: {
    has_exif: boolean;
    captured_at: string | null;
    gps_latitude: number | null;
    gps_longitude: number | null;
  } | null;
  annotations: { id: string; annotation_type: string; points: number[][]; label: string }[];
  width: number | null;
  height: number | null;
};

export type DamagedPart = {
  id: string;
  canonical_part: string;
  display_name: string;
  damage_type: string;
  severity: string;
  confidence: number | null;
  bounding_box: { x: number; y: number; w: number; h: number } | null;
  recommended_action: string;
  action_rationale: string | null;
  explanation: string | null;
  customer_reported: boolean;
  ai_detected: boolean;
  agreement: string;
  price: MoneyRange | null;
};

export type EstimateLine = {
  canonical_part: string;
  display_name: string;
  action: string;
  part_price_available: boolean;
  part_price_min: number | null;
  part_price_max: number | null;
  labour_hours: number | null;
  labour_min: number;
  labour_max: number;
  paint_min: number;
  paint_max: number;
  line_min: number;
  line_max: number;
  currency: string;
  basis: string;
  price_source_count: number;
};

export type Estimate = {
  claim_id: string;
  total: MoneyRange;
  labour_min: number | null;
  labour_max: number | null;
  paint_min: number | null;
  paint_max: number | null;
  parts_subtotal_min: number | null;
  parts_subtotal_max: number | null;
  lines: EstimateLine[];
  is_partial: boolean;
  unpriced_parts: string[];
  damage_to_value_ratio: number | null;
  calculation_notes: string | null;
  disclaimer: string;
  agent_adjusted_min: number | null;
  agent_adjusted_max: number | null;
  agent_adjustment_reason: string | null;
};

export type Assessment = {
  claim_id: string;
  status: ClaimStatus;
  vehicle: {
    make: string | null;
    model: string | null;
    year: number | null;
    color: string | null;
    confidence: number | null;
    registration_number: string | null;
    ocr_confidence: number | null;
    conflict_with_customer: boolean;
    conflict_detail: string | null;
  } | null;
  damaged_parts: DamagedPart[];
  reconciliation: {
    customer_reported: string[];
    ai_detected: string[];
    confirmed_by_both: string[];
    ai_only: string[];
    customer_only: string[];
    summary: string;
    manual_verification_recommended: boolean;
  } | null;
  summary_text: string | null;
  stage_confidences: Record<string, number>;
  overall_confidence: number | null;
  manual_review_required: boolean;
  manual_review_reasons: string[];
  notes: string[];
  disclaimer: string;
};

export type ClaimDetail = {
  id: string;
  claim_number: string;
  status: ClaimStatus;
  priority: string;
  created_at: string;
  submitted_at: string | null;
  ai_completed_at: string | null;
  customer_name: string | null;
  customer_email: string | null;
  customer_phone: string | null;
  policy_number: string | null;
  vehicle: Record<string, string | number | null>;
  accident_datetime: string | null;
  accident_description: string | null;
  customer_vehicle_description: string | null;
  customer_reported_parts: string[];
  customer_free_text_parts: string | null;
  images: ClaimImage[];
  assessment: Assessment | null;
  estimate: Estimate | null;
  market_data: {
    vehicle_label: string | null;
    valuation: MoneyRange;
    confidence_reason: string | null;
    sources: {
      source_name: string;
      url: string | null;
      listing_title: string | null;
      price: number;
      currency: string;
      retrieved_at: string;
    }[];
  } | null;
  part_prices: {
    damaged_part_id: string;
    canonical_part: string;
    display_name: string;
    price: MoneyRange;
    dominant_grade: string | null;
    confidence_reason: string | null;
    sources: {
      id: string;
      source_name: string;
      url: string | null;
      product_name: string;
      vehicle_compatibility: string | null;
      part_grade: string;
      price: number;
      currency: string;
      retrieved_at: string;
      excluded_from_summary: boolean;
    }[];
  }[];
  location: {
    latitude: number;
    longitude: number;
    address: string | null;
    city: string | null;
    source: string;
  } | null;
  fraud_signals: { signal_code: string; risk_level: string; description: string }[];
  notes: { id: string; body: string; visibility: string; created_at: string; author_name: string | null }[];
  timeline: { at: string; kind: string; title: string; detail: string | null; actor_name: string | null }[];
  manual_review_required: boolean;
  manual_review_reasons: string[];
  pipeline_stage: string | null;
  pipeline_progress: Record<string, { status: string; label: string; step: number; of: number }>;
};

export type ClaimStatusPayload = {
  claim_id: string;
  status: ClaimStatus;
  pipeline_stage: string | null;
  progress: Record<string, { status: string; label: string; step: number; of: number }>;
  ai_completed_at: string | null;
  manual_review_required: boolean;
};

export type PartCatalogItem = { code: string; display_name: string; group: string };
