# v01.08 UI/UX Screen Inventory

This inventory was completed before implementation. v01.08 is a workflow and presentation release: existing business rules, persistence, verification gates, pricing calculations, exports, and outreach safety behavior remain authoritative.

## Shared Shell

| Area | Purpose | Primary action | Current problems | v01.08 target | Reusable components |
| --- | --- | --- | --- | --- | --- |
| Main window | Route the operator between workstations | Act on the current page | Flat list navigation, no identity, no page context, every page wrapped in a scroll area, no command hierarchy | Branded grouped sidebar, persistent top command bar, page title/description, one page-level primary action, direct page container without unnecessary nested scrolling | App shell, sidebar item/group, page header, command button, toast host |
| Global feedback | Explain successful and failed actions | Continue working | Routine success relies on modal dialogs or silent updates; technical failures can dominate | Inline banners and short-lived toasts for routine feedback; dialogs only for meaningful errors/destructive confirmation | InfoBanner, Toast, ConfirmDialog |

## Main Navigation Pages

| Page | Purpose | Primary action | Secondary actions | Current UX problems | v01.08 layout | Reusable components |
| --- | --- | --- | --- | --- | --- | --- |
| First-Run Setup | Explain the product boundary and configuration state | Start first search | Open Settings, review paths | Read-only text block; no hierarchy or configuration badges | Welcome panel, three-step start path, configuration-state cards, compliance note | PageHeader, StateCard, InfoBanner, EmptyState |
| Dashboard | Answer what needs attention today | New Search / open next work item | View all leads, open follow-up, inspect activity | Passive grid plus two large text boxes; no actionable prioritization | Compact Today metrics, Today's Work queue, Top Opportunities table, Recent Activity | MetricCard, WorkItem, ScoreBadge, StatusBadge, DataTable, EmptyState |
| Lead Searches | Start a demo or live market search | New Search | View run status/history | Abrupt title, generic status box, little explanation of demo/live state | Page header, mode/config banner, primary New Search action, progress stage panel, recent runs link | PageHeader, InfoBanner, ProgressPanel |
| Run History | Review previous search runs | Refresh / inspect recent runs | — | Bare table and button; completion shown as yes/no | Compact sortable run table with state badges and an empty state | DataTable, StatusBadge, EmptyState |
| Leads | Scan and filter all opportunities | New Search / open lead | Search, status/verification/niche/score filters, clear filters | Eleven columns include internal IDs and long fields; limited filters; raw status text; weak selection | Global filter toolbar and focused default columns: Growth, Business, Category, Location, Website, Reviews, Status, Verification, Follow-up | PageHeader, FilterToolbar, DataTable, ScoreBadge, StatusBadge, EmptyState |
| Review Queue | Rapidly qualify or reject unreviewed leads | Review selected / Next Lead | Qualify, needs review, reject, ready for outreach | Reuses full Leads table and opens a modal for every lead; not inbox-like | Left queue plus right review summary where practical; fast open/next actions and explicit verification blockers | ReviewQueue, LeadPreview, VerificationProgress, RevenueLeakCard, EmptyState |
| Pipeline | Manage follow-ups and current sales state | Schedule follow-up / open selected lead | Quick status changes and due filters | Five equal action buttons; no due filters; due state is plain text; ID-heavy table | Overdue/Today/Upcoming/None filters, due metrics, compact table, one primary follow-up action and secondary status menu | PageHeader, MetricCard, DueBadge, StatusBadge, DataTable, ActionToolbar |
| Outreach | Review and approve grounded drafts | Approve selected draft | Edit, copy approved, unapprove, open lead | Recreates up to 30 full editors vertically; extremely tall; approval state easy to miss | Split view: draft list left, selected draft reader/editor summary right, dominant approval/copy state | SplitPane, StatusBadge, InfoBanner, EmptyState, ActionToolbar |
| Prompt Paste | Parse manually pasted AI-assisted comparison text locally | Parse answer | Clear input | Functional but visually isolated; no clear local/privacy state | Two-panel input/result workspace with local-only banner and empty result state | PageHeader, InfoBanner, SectionHeader |
| Industry Intelligence | Understand observed niche patterns in collected samples | Refresh | Export HTML | Large monospaced-style text output and two equal buttons | Summary header, sample disclaimer, focused output surface, primary refresh and secondary export | PageHeader, InfoBanner, ActionToolbar, ContentCard |
| Pricing Intelligence | Maintain private seller proof/history and interpret pricing | Record Offer | Add Proof, analyze lead, export private CSV | Database-admin feel; text-heavy metrics; recommendation hierarchy weak; wide raw tables | Metric overview, clear private-data banner, polished Project Value vs Seller Ask panel, filtered proof rows, outcome badges, grouped reasoning | MetricCard, PricingRecommendationPanel, StatusBadge, DataTable, ProofCard, EmptyState, SectionHeader |
| Reports | Generate and open deliverables | Open Reports Folder / generate selected output | Reports, comparisons, mockups, proposals, sites, packages, CSV | Seven equally weighted buttons and a text path dump | Report library/action catalog with one primary open-folder action and grouped generation actions | PageHeader, ActionCard, EmptyState, Toast |
| Suppression List | Prevent prohibited contact | Add suppression entry | Review current suppression state | Input plus silent status text; no context on consequence | Clear danger/info banner, compact input toolbar, current-state feedback | PageHeader, InfoBanner, ActionToolbar |
| Settings landing | Show configuration state and route to editor | Open Settings | Open logs, export diagnostics | Three equivalent buttons and generic copy | API status cards, local path summary, primary Settings action, secondary system tools | PageHeader, StateCard, ActionToolbar |
| Activity Log | Review durable operator/system history | Filter activity | Refresh | Plain text stream; no lead/action/date filtering | Table with Time, Lead, Action, Details plus action/lead search filters | PageHeader, FilterToolbar, DataTable, StatusBadge, EmptyState |

## Lead Detail Dialog

| Area/tab | Purpose | Primary action | Current problems | v01.08 target | Components |
| --- | --- | --- | --- | --- | --- |
| Lead shell/header | Command center for one prospect | Take next action | Business identity and status are buried inside tabs; 11 tabs and a separate Actions dump | Business/category/location header, Growth and status badges, Website/Maps/Contact/Proposal primary actions, summary strip | LeadHeader, ScoreBadge, StatusBadge, SummaryMetric, ActionToolbar |
| Overview | Explain why this is an opportunity | Review/qualify | Plain HTML label with raw joined signals | Opportunity summary, top Revenue Leak cards, recommended next actions, business/CRM side panel | RevenueLeakCard, InfoCard, VerificationProgress |
| Owner Mode | Prepare the sales conversation | Use opening/price language | One long text block | Grouped Opportunity, What to Say, Pricing, Verify Before Calling sections | SectionHeader, PricingRecommendationPanel, InfoBanner |
| Verification | Satisfy outreach prerequisites | Save checklist | Checkboxes lack progress/blocker hierarchy | Required/optional groups, progress bar, explicit Outreach Blocked banner and missing requirements | VerificationProgress, StatusBadge, InfoBanner |
| Lead & CRM | Maintain facts, owner, tags, status, follow-up | Save lead | Large flat form and date validation only after save | Grouped business, pipeline, follow-up, and notes sections with inline date hint/error | FormSection, FieldMessage, ActionToolbar |
| Business Opportunity Analysis | Inspect audit findings/evidence | Open screenshots/evidence | Raw HTML dump and filesystem-oriented screenshot actions | Revenue leaks first, strengths second, rendered/raw state banners, Desktop/Mobile screenshot tabs with open-full-size | RevenueLeakCard, ScreenshotPanel, InfoBanner |
| Google Presence | Review public profile fields | Verify facts | Flat HTML facts | Compact labeled facts and verification reminder | DefinitionCard, InfoBanner |
| Competitors | Review/approve comparable competitors | Save competitor review | Repeating labels/checkboxes with weak grouping | Compact competitor rows/cards, clear approval state, evidence notes | CompetitorCard, StatusBadge, SectionHeader |
| Starting Offer | Review package inputs and generated offer | Save/regenerate | Form and generated text have equal visual weight | Inputs in secondary panel; generated scope and next step as primary content | FormSection, ContentCard, InfoBanner |
| Outreach | Review drafts for this lead | Approve/copy selected | Every draft renders a full editor and three verbose buttons | Draft selector plus focused content, explicit approval blocker/state | SplitPane, StatusBadge, ActionToolbar |
| Contact History | Maintain interactions/follow-up | Add interaction | Repeating full text entries and per-row buttons | Timeline/table with method, direction, outcome, follow-up and compact actions | TimelineRow, StatusBadge, ConfirmDialog |
| Pricing (new consolidated view) | Explain Project Value and seller ask | Record Presented Offer | Pricing is split across Owner Mode, Starting Offer, Actions, and modal guidance | Dedicated visual recommendation and grouped reasoning without changing pricing logic | PricingRecommendationPanel, SectionHeader, InfoBanner |
| Reports/Actions | Generate operator/customer artifacts | Generate selected deliverable | 20 equally weighted buttons in a grid | Grouped customer deliverables, internal tools, lead state, and danger zone; primary proposal action visible | ActionCard, ActionToolbar, ConfirmDialog |

## Dialogs

| Dialog | Purpose | Primary action | Current problems | v01.08 target | Components |
| --- | --- | --- | --- | --- | --- |
| New Search | Configure demo/live search | Run Search | One long 18-row form; advanced audits face every user; no sections | Market, Lead Quality, and basic mode visible; Advanced Options disclosure for audit depth/outputs; live configuration banner | DialogHeader, FormSection, InfoBanner, ActionToolbar |
| Settings | Edit API, local, audit, and sender settings | Save Settings | One flat form; secret state unclear; inconsistent indentation | General, API Connections, Outreach Identity, Audit tabs/sections; masked keys and Configured/Not configured labels | DialogHeader, FormSection, StateCard, FieldMessage |
| Contact Interaction | Add/edit real contact history | Save Interaction | Flat form; no visual date guidance; no cancel action | Grouped interaction and follow-up fields, inline format hints, standard Save/Cancel footer | DialogHeader, FormSection, FieldMessage, ActionToolbar |
| Outreach Editor | Edit a draft and revoke approval | Save Draft | Approval revocation is invisible until after save | Explicit warning that edits require reapproval; focused subject/body editor | DialogHeader, InfoBanner, ActionToolbar |
| Offer History | Record recommendation, override, negotiation, and outcome | Save Offer | Long form; snapshot context is a sentence; outcome dependencies unclear | Pricing context panel, grouped Prospect/Scope/Pricing/Outcome sections, visible Won closed-amount rule | DialogHeader, PricingSummary, FormSection, FieldMessage |
| Seller Proof | Add/edit real proof | Save Proof | Database-style long form; verification meaning unclear | Identity, evidence detail, and verification sections; verification help banner | DialogHeader, FormSection, InfoBanner |
| Follow-up | Schedule or clear a date | Save | Popup validation only | Inline format hint/error and standard footer | DialogHeader, FieldMessage, ActionToolbar |
| Destructive confirmations | Protect material deletion/suppression | Confirm destructive action | Generic QMessageBox wording/styling | Consistent title, consequence, Cancel default, red destructive button | ConfirmationDialog |

## Reusable Component Plan

The component package will centralize behavior and visual roles rather than duplicating per-widget style strings:

- `PageHeader`: page title, supporting description, contextual primary/secondary actions.
- `MetricCard`: compact label/value/supporting text with semantic accent.
- `SectionHeader`: consistent section title and optional supporting action.
- `StatusBadge`: status/outcome/due/verification label with text plus semantic color.
- `ScoreBadge`: Growth Score number and non-probabilistic opportunity band.
- `EmptyState`: useful explanation and optional next action.
- `DataTable`: common selection, header, row height, sorting, elision/tooltips, and resize behavior.
- `ActionToolbar`: one primary action plus subordinate secondary/tertiary/danger roles.
- `InfoBanner`: info/success/warning/error/private states.
- `PricingRecommendationPanel`: visually separated Project Value and Easy/Recommended/Stretch seller asks.
- `VerificationProgress`: numerator/denominator, progress, and explicit missing blockers.
- `RevenueLeakCard`: outcome-oriented finding, impact, evidence, and evidence action.
- `FieldMessage`: inline help/error text for forms.
- `Toast`: non-modal routine success feedback.
- `ConfirmationDialog`: consistent destructive confirmation.

## Scope Decisions

- Required: polished light theme. Dark mode is deferred rather than shipped incomplete.
- Required: table-first Pipeline. Board view is deferred because it is optional and would add risk without improving the core acceptance path as much as table polish.
- Required: single main content region. Tables retain their own scrolling; broad page scroll is used only where content cannot fit naturally.
- Required: all existing safety gates and manual approval/recording behavior remain intact.
- No new database tables or business calculations are planned for v01.08.
