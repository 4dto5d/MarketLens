from __future__ import annotations

import json

# ruff: noqa: E501
import webbrowser
from html import escape
from pathlib import Path

from sqlalchemy.orm import Session

from local_presence_miner.config import AppConfig
from local_presence_miner.database.repositories import loads
from local_presence_miner.database.schema import Lead
from local_presence_miner.services.mockup_service import infer_services
from local_presence_miner.services.pricing_menu import SERVICE_TIERS
from local_presence_miner.services.report_service import lead_artifact_slug
from local_presence_miner.services.website_builder_prompt_service import WebsiteBuilderPromptService

PRODUCTION_CHECKLIST = [
    "Business identity",
    "Phone",
    "Address",
    "Hours",
    "Service area",
    "Services",
    "Logo and brand assets",
    "Licensed photos",
    "Verified testimonials",
    "Licenses and credentials",
    "Form destination",
    "Chat integration or removal",
    "Privacy policy",
    "Terms where needed",
    "Analytics",
    "Schema",
    "Domain",
    "Hosting and SSL",
    "Desktop QA",
    "Mobile QA",
]


class StaticSiteService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def export_site(self, lead: Lead, session: Session | None = None) -> Path:
        folder = self.config.output_dir / "site_exports" / lead_artifact_slug(lead)
        assets = folder / "assets"
        folder.mkdir(parents=True, exist_ok=True)
        assets.mkdir(parents=True, exist_ok=True)
        services = infer_services(lead.category)
        signals = loads(lead.target_signals_json, [])
        (folder / "index.html").write_text(build_index_html(lead, services, signals), encoding="utf-8")
        (folder / "styles.css").write_text(build_css(), encoding="utf-8")
        builder_prompt = None
        if session is not None:
            bundle = WebsiteBuilderPromptService(self.config).build_bundle(session, lead)
            builder_prompt = bundle.generic
            (folder / "AI_WEBSITE_BUILDER_PROMPT.md").write_text(bundle.generic, encoding="utf-8")
            (folder / "LOVABLE_PROMPT.md").write_text(bundle.lovable, encoding="utf-8")
            (folder / "CANVA_WEBSITE_PROMPT.md").write_text(bundle.canva, encoding="utf-8")
        (folder / "README_FOR_BUILDER.md").write_text(
            build_builder_readme(lead, services, signals, builder_prompt),
            encoding="utf-8",
        )
        (folder / "BUILD_STATUS.json").write_text(
            json.dumps(
                {
                    "status": "Concept",
                    "production_ready": False,
                    "required_before_launch": PRODUCTION_CHECKLIST,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (assets / "PUT_HERO_VIDEO_HERE.txt").write_text(
            "Drop a 7-10 second muted looping MP4 here as hero-video.mp4. Use real business footage or properly licensed stock footage.",
            encoding="utf-8",
        )
        return folder

    def open_site(self, lead: Lead, session: Session | None = None) -> Path:
        folder = self.export_site(lead, session=session)
        webbrowser.open((folder / "index.html").resolve().as_uri())
        return folder


def build_index_html(lead: Lead, services: list[str], signals: list[str]) -> str:
    business_name = escape(lead.name, quote=True)
    category = escape(lead.category, quote=True)
    phone_raw = lead.phone or ""
    phone = escape(phone_raw or "Call today", quote=True)
    phone_href = escape(phone_raw, quote=True)
    city_line = escape(lead.address or "Serving the local area", quote=True)
    schema_json = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": lead.name,
            "telephone": lead.phone,
            "address": lead.address,
            "url": "",
        },
        ensure_ascii=False,
    ).replace("</", "<" + "\\/")
    service_cards = "".join(
        f"""
        <article class="service-card">
          <span>0{index}</span>
          <h3>{escape(service)}</h3>
          <p>Clear scope, fast response expectations, and a simple next step for customers who are ready to act.</p>
        </article>
        """
        for index, service in enumerate(services[:6], start=1)
    )
    signal_items = "".join(f"<li>{escape(str(signal))}</li>" for signal in signals) or "<li>Verify hours, photos, services, reviews, and contact flow.</li>"
    pricing_cards = "".join(
        f"""
        <article class="price-card">
          <h3>{tier.name}</h3>
          <p class="price">{tier.price_range}</p>
          <p>{tier.best_for}</p>
          <ul>{"".join(f"<li>{item}</li>" for item in tier.deliverables[:4])}</ul>
        </article>
        """
        for tier in SERVICE_TIERS
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{business_name}</title>
  <meta name="description" content="{business_name} local {category} website starter concept.">
  <link rel="stylesheet" href="styles.css">
  <script type="application/ld+json">{schema_json}</script>
</head>
<body>
  <aside class="build-status" role="note"><strong>CONCEPT SITE</strong> — unaffiliated draft; business facts, form integration, legal review, and QA are required before launch.</aside>
  <header class="topbar">
    <a class="brand" href="#top">{business_name}</a>
    <nav aria-label="Main navigation">
      <a href="#services">Services</a>
      <a href="#proof">Proof</a>
      <a href="#process">Process</a>
      <a href="#quote">Quote</a>
    </nav>
    <a class="phone" href="tel:{phone_href}">{phone}</a>
  </header>
  <main id="top">
    <section class="hero band">
      <video class="hero-video" autoplay muted loop playsinline poster="assets/hero-poster.jpg">
        <source src="assets/hero-video.mp4" type="video/mp4">
      </video>
      <div class="hero-overlay"></div>
      <div>
        <p class="eyebrow">Local {category} • {city_line}</p>
        <h1>Fast, trustworthy local help with a quote path customers can use in seconds.</h1>
        <p class="lead">A polished local presence should answer three questions immediately: can I trust them, do they handle my problem, and how do I contact them right now?</p>
        <div class="actions">
          <a class="button" href="tel:{phone_href}">Call {phone}</a>
          <a class="button secondary" href="#quote">Request a Quote</a>
        </div>
        <ul class="trust-row">
          <li>Mobile-first contact flow</li>
          <li>Service-area clarity</li>
          <li>Review and job-photo proof</li>
        </ul>
      </div>
      <aside class="hero-panel">
        <h2>Quick Response</h2>
        <p>Use this panel for emergency hours, guarantee language, service area, or a real owner photo.</p>
        <dl>
          <div><dt>Call</dt><dd>{phone}</dd></div>
          <div><dt>Area</dt><dd>{city_line}</dd></div>
          <div><dt>Next step</dt><dd>Send details and photos</dd></div>
        </dl>
      </aside>
    </section>

    <section id="services">
      <h2>Services</h2>
      <p class="section-intro">Each service card should be rewritten with the exact jobs this business wants most.</p>
      <div class="grid">{service_cards}</div>
    </section>

    <section id="proof" class="split">
      <div>
        <h2>Trust Proof To Add</h2>
        <ul>
          <li>Recent job photos or before/after examples</li>
          <li>Real review highlights</li>
          <li>Owner/team photo and service-area proof</li>
          <li>Licenses, guarantees, warranties, or process notes where true</li>
        </ul>
      </div>
      <div>
        <h2>Google Presence Fixes</h2>
        <ul>{signal_items}</ul>
      </div>
    </section>

    <section id="process">
      <h2>Simple Customer Process</h2>
      <div class="steps">
        <article><strong>1</strong><h3>Send the details</h3><p>Customer calls or sends a short quote request with ZIP code, urgency, and photos.</p></article>
        <article><strong>2</strong><h3>Get a clear next step</h3><p>The business confirms fit, timing, and what information is needed before a visit.</p></article>
        <article><strong>3</strong><h3>Approve the work</h3><p>Customer receives a simple scope and knows how to approve or schedule.</p></article>
      </div>
    </section>

    <section class="split">
      <div>
        <h2>Why Customers Choose Us</h2>
        <ul>
          <li>Clear communication before the appointment</li>
          <li>Local service-area focus</li>
          <li>Photo-friendly estimate workflow</li>
          <li>Review proof and transparent next steps</li>
        </ul>
      </div>
      <div>
        <h2>FAQ</h2>
        <details open><summary>How fast can someone respond?</summary><p>Replace this with true hours, callback expectations, and emergency availability.</p></details>
        <details><summary>What areas do you serve?</summary><p>List cities, ZIP codes, and nearby neighborhoods.</p></details>
        <details><summary>Can I send photos?</summary><p>Encourage photos when they help quote or triage the job.</p></details>
      </div>
    </section>

    <section id="quote" class="quote">
      <h2>Request a Quote</h2>
      <form>
        <label>Name <input name="name" placeholder="Your name"></label>
        <label>Phone <input name="phone" placeholder="Best callback number"></label>
        <label>ZIP code <input name="zip" placeholder="Service ZIP"></label>
        <label>Service needed <select name="service">{"".join(f"<option>{escape(service)}</option>" for service in services[:6])}</select></label>
        <label>What is going on? <textarea name="message" placeholder="Describe the job, timing, and any details that matter."></textarea></label>
        <button type="button">Send Request</button>
      </form>
      <p class="form-note">This static export uses non-submitting form markup. Connect it to the owner's form tool, email service, CRM, or website builder before launch.</p>
    </section>

    <section id="pricing">
      <h2>Optional Build Packages</h2>
      <p class="section-intro">Use this section internally or turn it into an owner-facing pricing page after choosing the right scope.</p>
      <div class="pricing-grid">{pricing_cards}</div>
    </section>
  </main>
  <button class="chat-bubble" type="button" aria-label="Open question helper" aria-controls="chat-panel" aria-expanded="false">
    <span>Ask a question</span>
    <small>Optional AI/chat upgrade</small>
  </button>
  <aside id="chat-panel" class="chat-panel" aria-label="Chat placeholder" hidden>
    <button class="chat-close" type="button" aria-label="Close question helper">Close</button>
    <h2>Need help choosing a service?</h2>
    <p>This is a front-end chat bubble placeholder. Connect it to human chat, a contact form, or a real AI provider before launch.</p>
    <label>Your question <textarea placeholder="Example: Do you handle emergency repairs?"></textarea></label>
    <button type="button">Send Question</button>
  </aside>
  <div class="mobile-cta"><a href="tel:{phone_href}">Call</a><a href="#quote">Quote</a></div>
  <script>
    const bubble = document.querySelector('.chat-bubble');
    const panel = document.querySelector('.chat-panel');
    const closeButton = document.querySelector('.chat-close');
    function setChatOpen(open) {{ panel.hidden = !open; bubble.setAttribute('aria-expanded', String(open)); }}
    bubble.addEventListener('click', () => setChatOpen(panel.hidden));
    closeButton.addEventListener('click', () => setChatOpen(false));
  </script>
</body>
</html>
"""


def build_css() -> str:
    return """:root { --ink: #172033; --muted: #5b6678; --line: #dce4ef; --brand: #184f8f; --brand-dark: #113252; --accent: #f2bd3f; --paper: #ffffff; --wash: #f4f7fb; }
* { box-sizing: border-box; }
body { margin: 0; font-family: Arial, sans-serif; color: var(--ink); background: var(--wash); line-height: 1.5; }
.build-status { padding: 9px 18px; text-align: center; background: #fff1c7; border-bottom: 1px solid #d8b75d; color: #5d4710; font-size: 13px; }
a { color: inherit; }
.topbar { position: sticky; top: 0; z-index: 10; display: flex; gap: 18px; justify-content: space-between; align-items: center; padding: 14px 28px; background: rgba(255,255,255,.96); border-bottom: 1px solid var(--line); backdrop-filter: blur(8px); }
.brand { font-weight: 800; text-decoration: none; font-size: 18px; }
nav { display: flex; gap: 14px; color: var(--muted); font-size: 14px; }
nav a { text-decoration: none; }
.phone, .button, button { color: white; background: var(--brand); padding: 11px 15px; border-radius: 6px; text-decoration: none; font-weight: 800; border: 0; cursor: pointer; }
main { max-width: 1160px; margin: 0 auto; padding: 28px; }
.band { margin-top: 18px; }
.hero { position: relative; overflow: hidden; display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 22px; background: linear-gradient(135deg, var(--brand-dark), var(--brand)); color: white; padding: 46px; border-radius: 8px; min-height: 560px; align-items: end; }
.hero > *:not(.hero-video):not(.hero-overlay) { position: relative; z-index: 2; }
.hero-video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: .46; }
.hero-overlay { position: absolute; inset: 0; background: linear-gradient(90deg, rgba(17,50,82,.94), rgba(17,50,82,.64) 52%, rgba(17,50,82,.36)); z-index: 1; }
.hero h1 { font-size: 44px; line-height: 1.05; margin: 8px 0 16px; max-width: 760px; }
.lead { max-width: 690px; color: #dce7f4; font-size: 18px; }
.eyebrow { text-transform: uppercase; letter-spacing: .06em; font-size: 13px; color: #cfe0f6; font-weight: 800; }
.actions { margin-top: 20px; display: flex; gap: 10px; flex-wrap: wrap; }
.button.secondary { background: var(--accent); color: var(--ink); }
.trust-row { display: flex; flex-wrap: wrap; gap: 10px; padding: 0; margin: 24px 0 0; list-style: none; }
.trust-row li { border: 1px solid rgba(255,255,255,.3); border-radius: 999px; padding: 7px 10px; color: #eef5ff; }
.hero-panel { background: white; color: var(--ink); border-radius: 8px; padding: 22px; align-self: stretch; }
.hero-panel dl { margin: 0; }
.hero-panel div { border-top: 1px solid var(--line); padding: 12px 0; }
.hero-panel dt { color: var(--muted); font-size: 13px; }
.hero-panel dd { margin: 0; font-weight: 800; }
section { margin: 26px 0; }
section > h2 { font-size: 30px; margin-bottom: 8px; }
.section-intro { color: var(--muted); max-width: 680px; }
.grid, .steps, .pricing-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px; }
.service-card, .steps article, .split > div, .quote, .price-card { background: var(--paper); border: 1px solid var(--line); border-radius: 8px; padding: 20px; box-shadow: 0 10px 24px rgba(24, 79, 143, .07); }
.price-card .price { color: var(--brand); font-size: 22px; font-weight: 900; }
.service-card span, .steps strong { color: var(--brand); font-weight: 900; }
.split { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }
details { border-top: 1px solid var(--line); padding: 12px 0; }
summary { cursor: pointer; font-weight: 800; }
form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
label { display: grid; gap: 6px; font-weight: 800; }
input, select, textarea { width: 100%; border: 1px solid var(--line); border-radius: 6px; padding: 11px; font: inherit; }
textarea { min-height: 120px; grid-column: 1 / -1; }
form label:last-of-type, form button, .form-note { grid-column: 1 / -1; }
.form-note { color: var(--muted); font-size: 14px; }
.mobile-cta { display: none; }
.chat-bubble { position: fixed; right: 22px; bottom: 22px; display: grid; gap: 2px; border-radius: 999px; padding: 13px 18px; box-shadow: 0 12px 28px rgba(0,0,0,.22); z-index: 18; }
.chat-bubble small { color: #dce7f4; font-weight: 400; }
.chat-panel { position: fixed; right: 22px; bottom: 88px; width: min(360px, calc(100vw - 44px)); background: white; border: 1px solid var(--line); border-radius: 8px; padding: 18px; box-shadow: 0 20px 48px rgba(0,0,0,.2); z-index: 18; }
.chat-panel[hidden] { display: none; }
.chat-panel h2 { margin-top: 0; }
@media (max-width: 820px) {
  .topbar { display: block; }
  nav { margin: 10px 0; flex-wrap: wrap; }
  .hero { grid-template-columns: 1fr; padding: 28px; }
  .hero h1 { font-size: 34px; }
  form { grid-template-columns: 1fr; }
  .mobile-cta { position: fixed; left: 0; right: 0; bottom: 0; display: grid; grid-template-columns: 1fr 1fr; z-index: 20; }
  .mobile-cta a { text-align: center; padding: 14px; background: var(--brand); color: white; font-weight: 900; text-decoration: none; }
  .mobile-cta a + a { background: var(--accent); color: var(--ink); }
  .chat-bubble, .chat-panel { display: none; }
}
"""


def build_builder_readme(lead: Lead, services: list[str], signals: list[str], builder_prompt: str | None = None) -> str:
    return f"""# {lead.name} Static Website Starter

Build status: **Concept**. This is an unaffiliated starter export, not a production website. It can be opened locally, edited by hand, or pasted into a site builder that accepts HTML/CSS.

## Files

- `index.html`
- `styles.css`
- `BUILD_STATUS.json`

## Business

- Name: {lead.name}
- Category: {lead.category}
- Phone: {lead.phone or "not captured"}
- Website before export: {lead.website or "none listed"}

## Services To Verify

{chr(10).join(f"- {service}" for service in services)}

## Public Gaps To Address

{chr(10).join(f"- {signal}" for signal in signals) or "- Verify hours, services, photos, reviews, and contact flow."}

## AI Builder Prompts

When this export was created from a live database session, the folder also includes:

- `AI_WEBSITE_BUILDER_PROMPT.md` — platform-neutral, competitor-grounded prompt
- `LOVABLE_PROMPT.md` — Lovable-adapted version
- `CANVA_WEBSITE_PROMPT.md` — Canva Website-adapted version

The prompt is built from the target audit plus the selected competitor audits. Unknown facts remain marked for verification.

## Builder Prompt

{builder_prompt or f"Create a truthful local {lead.category} website concept using the public gaps listed above. Competitor context was not available for this export, so do not make competitor claims. Do not invent business facts, testimonials, credentials, pricing, service areas, or guarantees. Make the mobile contact path obvious and clearly mark anything that still needs owner verification."}

## Optional Chat / AI Bubble

The export includes a polished chat bubble placeholder. It is not a working AI assistant until connected to a provider.

Suggested pricing:

- Human-managed chat bubble: $250-$900 setup plus $100-$500/mo.
- Real AI answer bubble: $750-$2,500 setup plus API/platform costs plus $150-$750/mo.

Use real source docs, approved FAQs, handoff rules, and monthly review if AI is enabled.

## Hero Video Slot

The first screen supports a paid-looking muted background video.

Drop this file into `assets/`:

```text
hero-video.mp4
```

Best specs:

- 7-10 seconds
- muted
- looping-friendly
- 1920x1080 or 1280x720
- under 8-12 MB if possible
- real business footage or properly licensed stock footage

Examples:

- real estate: slow mansion/interior/exterior pan
- roofing: crew, roofline, inspection, truck arrival
- salon/barber: chair, tools, clean interior, finished work
- auto: shop bay, diagnostic, car lift, detail shot
- dental/medical: clean office, front desk, treatment room, smiling staff
"""
