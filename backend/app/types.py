from enum import StrEnum


class UserRole(StrEnum):
    OWNER = "owner"
    PARTNER = "partner"
    ANALYST = "analyst"
    VIEWER = "viewer"
    SERVICE = "service"


class OrgPlan(StrEnum):
    DEMO = "demo"
    STANDARD = "standard"


class SourceTier(StrEnum):
    PRIMARY = "primary"
    VERIFIED_THIRD_PARTY = "verified_third_party"
    AGGREGATOR = "aggregator"
    SELF_REPORTED = "self_reported"
    INFERRED = "inferred"


class SourceStatus(StrEnum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    NO_CREDENTIALS = "no_credentials"


class SignalKind(StrEnum):
    REPO_ACTIVITY = "repo_activity"
    RELEASE = "release"
    PACKAGE_PUBLISH = "package_publish"
    PAPER = "paper"
    PATENT = "patent"
    HACKATHON_RESULT = "hackathon_result"
    ACCELERATOR_COHORT = "accelerator_cohort"
    LAUNCH_POST = "launch_post"
    FORUM_POST = "forum_post"
    SOCIAL_POST = "social_post"
    PRESS = "press"
    JOB_POST = "job_post"
    FUNDING_FILING = "funding_filing"
    COMPANY_REGISTRY = "company_registry"
    DOMAIN_REGISTRATION = "domain_registration"
    TLS_CERTIFICATE = "tls_certificate"
    WEBSITE_CHANGE = "website_change"
    DECK_SLIDE = "deck_slide"
    INTERVIEW = "interview"
    APP_RELEASE = "app_release"
    DATASET_MODEL_PUBLISH = "dataset_model_publish"
    OTHER = "other"


class OpportunityStage(StrEnum):
    SOURCED = "sourced"
    SCREENING = "screening"
    SCREENED = "screened"
    DILIGENCE = "diligence"
    DECISION = "decision"
    DECIDED = "decided"
    ARCHIVED = "archived"


class OpportunityOrigin(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    MANUAL = "manual"


class DecisionKind(StrEnum):
    INVEST = "invest"
    PASS = "pass"
    WATCHLIST = "watchlist"
    NEEDS_HUMAN = "needs_human"


class AxisKind(StrEnum):
    FOUNDER = "founder"
    MARKET = "market"
    IDEA_VS_MARKET = "idea_vs_market"


class TrendKind(StrEnum):
    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"
    INSUFFICIENT_DATA = "insufficient_data"


class MarketStance(StrEnum):
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEAR = "bear"


class ClaimStatus(StrEnum):
    VERIFIED = "verified"
    CORROBORATED = "corroborated"
    CLAIMED = "claimed"
    CONTRADICTED = "contradicted"
    NOT_DISCLOSED = "not_disclosed"
    UNVERIFIABLE = "unverifiable"


class ClaimCategory(StrEnum):
    TRACTION = "traction"
    REVENUE = "revenue"
    TEAM = "team"
    MARKET = "market"
    PRODUCT = "product"
    TECHNOLOGY = "technology"
    FUNDING = "funding"
    LEGAL = "legal"
    OTHER = "other"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class OutreachStatus(StrEnum):
    SUGGESTED = "suggested"
    APPROVED = "approved"
    SENT = "sent"
    REPLIED = "replied"
    APPLIED = "applied"
    DECLINED = "declined"
    BOUNCED = "bounced"


class ApplicationStatus(StrEnum):
    RECEIVED = "received"
    PARSING = "parsing"
    SCREENING = "screening"
    NEEDS_INFO = "needs_info"
    IN_DILIGENCE = "in_diligence"
    DECIDED = "decided"
    REJECTED_PRESCREEN = "rejected_prescreen"
    ERROR = "error"


class Permission(StrEnum):
    READ = "read"
    SCREEN = "opportunities:screen"
    DECIDE = "opportunities:decide"
    THESIS_WRITE = "theses:write"
    ORG_ADMIN = "org:admin"
    ADMIN = "admin"


ROLE_PERMISSIONS: dict[UserRole, set[Permission]] = {
    UserRole.OWNER: set(Permission),
    UserRole.PARTNER: {
        Permission.READ,
        Permission.SCREEN,
        Permission.DECIDE,
        Permission.THESIS_WRITE,
    },
    UserRole.ANALYST: {Permission.READ, Permission.SCREEN},
    UserRole.VIEWER: {Permission.READ},
    UserRole.SERVICE: {Permission.READ, Permission.SCREEN, Permission.ADMIN},
}
