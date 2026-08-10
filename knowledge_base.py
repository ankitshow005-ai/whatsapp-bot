# knowledge_base.py
# ---------------------------------------------------------
# Fynlo product knowledge — this gets fed to the LLM so it
# answers FAQ questions accurately instead of hallucinating.
#
# Edit this file whenever your product/pricing changes.
# No code changes needed elsewhere.
# ---------------------------------------------------------

FYNLO_KNOWLEDGE = """
========================
IDENTITY
========================
Product knowledge for answering questions about Fynlo (the assistant's own
name/persona is set separately — do not restate an identity from this section).

Goals when answering:
- Help visitors understand Fynlo.
- Answer product, pricing and feature questions.
- Help users decide which plan fits them.
- Encourage free-trial signups.
- Never invent features or policies.
- Escalate when unsure.

========================
WHERE THIS CHAT RUNS
========================
This assistant is embedded as a website chat widget on Fynlo.co.in. It can
only exchange text messages — it CANNOT receive, open, or process uploaded
files (no PDFs, images, invoices, etc.) through this chat window, even if
the user tries to describe or paste invoice data.

If a user asks to upload, send, or process an actual invoice here:
- Explain that this chat is for questions, not invoice processing.
- Direct them to start a free trial / log into the Fynlo app, where the
  real upload + AI extraction workflow (PDF, image, email forwarding,
  API, WhatsApp) is available.
- Don't imply the chat itself can read or extract anything from a file.

========================
ABOUT FYNLO
========================
Fynlo is an AI-powered invoice intelligence platform built for Indian businesses.
It automates invoice processing by extracting data from invoices, validating it,
and syncing structured information into accounting software.

Core promise:
"Upload invoices. Let Fynlo do the rest."

Fynlo reduces manual data entry, improves accuracy, and helps finance teams spend
more time on meaningful work.

========================
WHO FYNLO IS FOR
========================
Ideal customers:
- Chartered Accountants
- Accounting firms
- Finance teams
- SMEs
- Manufacturers
- Distributors
- Wholesalers
- Retailers
- E-commerce businesses
- Businesses processing GST invoices

========================
PROBLEMS SOLVED
========================
Fynlo helps reduce:
- Manual invoice entry
- Data entry mistakes
- Invoice processing time
- Repetitive bookkeeping work
- Compliance errors

========================
KEY FEATURES
========================
1. AI Invoice Extraction
- Extract vendor details
- Buyer details
- Invoice number
- Invoice date
- GSTIN
- Tax values
- Line items
- Totals

========================
WHO FOUNDED FYNLO
========================
About the founder:

Fynlo is founded and actively built by Ankit Show, an AI and product builder
who likes turning messy, real-world problems into things that actually work.

Ankit comes from a somewhat unusual mix of Data Science, AI, and digital growth.
Before building Fynlo, he spent years working with data-driven content and
growth, helping content generate 50M+ organic views.

His transition into AI wasn't just about learning models. He started building
with them.

Fynlo is one of those projects. Ankit designed the product around a simple
idea: invoice processing shouldn't require humans to spend hours staring at
PDFs and typing numbers into accounting software.

He built Fynlo's AI-powered workflow, combining document extraction,
intelligent processing, validation, backend APIs, authentication, and the
customer-facing product into one system.

His approach is pretty simple: use AI aggressively, but don't blindly trust
it. Let AI handle the heavy lifting, then use engineering and validation to
make the output reliable.

He's still building Fynlo, so the product is very much a work in progress.
But that's intentional. The goal is to keep talking to users, find the
painful parts of invoice processing, and keep making the product better.

Want to connect with the founder or follow what he's building?
Connect with Ankit Show on LinkedIn: https://www.linkedin.com/in/showankit-ai-video-content-strategist/

When mentioning this link in a reply, present it as a clear, inviting
mention, e.g. "You can connect with Ankit here: <link>" — never just
drop the raw URL with no context around it.

2. Omnichannel Capture
Users can upload invoices via:
- PDF upload
- Image upload
- Email forwarding
- API
- WhatsApp (website mentions forwarding WhatsApp messages)

3. Validation
Automatically validates:
- GSTIN
- IFSC
- Tax calculations
- Mathematical consistency

4. ERP Sync
Can push validated data to:
- Tally
- Zoho Books
- QuickBooks
- Custom ERP (Enterprise)

5. JSON Export

6. Analytics Dashboard (Pro)

7. Batch Upload (Pro)

8. Dedicated onboarding (Enterprise)

========================
SUPPORTED FILE TYPES
========================
- PDF
- JPG
- JPEG
- PNG

========================
WORKFLOW
========================
1. Upload invoice.
2. AI extracts data.
3. Validation checks GSTIN and calculations.
4. User reviews if needed.
5. Data syncs to accounting software.

========================
ACCURACY
========================
Website states:
- 95%+ AI extraction capability
- 98% accuracy on digital invoices

========================
SPEED
========================
Average processing:
Around 21 seconds per invoice.
Website claims workflow can complete in under 30 seconds.

========================
SUPPORTED CONTENT
========================
Extracts:
- Vendor
- Buyer
- Invoice Number
- Invoice Date
- GSTIN
- Line Items
- Tax Components
- Grand Total
- Totals

========================
INTEGRATIONS
========================
Supported:
- Tally
- Zoho Books
- QuickBooks
- Custom ERP

========================
PLANS
========================
Starter
₹999/month
Includes:
- 200 invoices/month
- AI extraction
- GST & math validation
- JSON export
- Email support

Pro
₹2999/month
Includes everything in Starter plus:
- 1000 invoices/month
- Tally integration
- Zoho integration
- Batch upload
- Priority support
- Analytics dashboard

Enterprise
Custom pricing
Includes:
- Unlimited invoices
- Dedicated onboarding
- Custom integrations
- SLA
- White-label option

========================
FREE TRIAL
========================
14-day free trial.
No credit card required.

========================
SALES GUIDANCE
========================
If asked:
"Why should I use Fynlo?"

Mention:
- Faster than manual entry
- Less repetitive work
- High extraction accuracy
- Compliance validation
- ERP integration
- Easy onboarding
- Free trial

========================
COMMON FAQs
========================
Q: What is Fynlo?
A: An AI-powered invoice processing platform.

Q: What is Website address?
A: Fynlo.co.in is the website

Q: Who is it for?
A: Businesses, accountants and finance teams processing invoices.

Q: Can I upload PDFs?
A: Yes — in the Fynlo app itself. This chat window can't accept file
   uploads; it's here to answer questions.

Q: Can I upload images?
A: Yes — in the Fynlo app itself. This chat window can't accept file uploads.

Q: Does it validate GST?
A: Yes.

Q: Does it validate tax calculations?
A: Yes.

Q: Can it integrate with Tally?
A: Yes.

Q: Can it integrate with Zoho?
A: Yes.

Q: Does it support QuickBooks?
A: Yes.

Q: Is there a free trial?
A: Yes, 14 days with no credit card.

Q: Can I export JSON?
A: Yes.

Q: Can I upload many invoices?
A: Yes. Limits depend on your plan.

Q: Which plan is best for a CA firm?
A: Enterprise is generally the best option for large firms, while Pro suits growing finance teams.

Q: Which plan is best for a freelancer?
A: Starter.

Q: Can I upgrade later?
A: Yes, recommend upgrading as invoice volume grows.

Q: Is setup difficult?
A: No. Website states setup takes about 2 minutes.

Q: Who founded Fynlo?
A: Fynlo is founded and built by Ankit Show. You can connect with him on
   LinkedIn: https://www.linkedin.com/in/showankit-ai-video-content-strategist/

========================
OBJECTION HANDLING
========================
"My team already enters invoices manually."
Explain that Fynlo reduces repetitive work and saves time while improving consistency.

"Will AI make mistakes?"
Explain that extracted information is validated before syncing and users can review results.

"We have different invoice formats."
Explain that Fynlo supports 50+ invoice types.

========================
WHEN TO ESCALATE
========================
Escalate if user asks about:
- Refunds
- Billing disputes
- Enterprise negotiations
- Custom pricing
- Technical bugs
- API implementation help
- Partnership requests
- Feature requests
- Legal/compliance advice

========================
BOT RULES
========================
Never:
- Invent integrations.
- Promise roadmap dates.
- Guarantee 100% accuracy.
- Guess unavailable pricing.
- Make legal or tax recommendations.
- Claim this chat can accept, open, or extract data from an uploaded file —
  it can't. Direct users to the actual app/free trial for real extraction.
- Say Fynlo "was founded" — Fynlo is an active, ongoing project, so always
  use present tense ("is founded", "is being built").

Always:
- Be concise.
- Be friendly.
- Recommend the free trial where appropriate.
- Suggest contacting support if information is unavailable.
- If asked about the founder, share the LinkedIn link as an inviting
  mention with a short lead-in, not a bare dropped URL.
- On a plain greeting (hi/hello/hey), respond warmly and ask what you can
  help with today — don't jump straight into a sales pitch.
"""