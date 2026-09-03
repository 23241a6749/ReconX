# Free Groq + Render deployment

This is the recommended zero-cost buildathon setup. The deterministic reconciliation
engine remains the authority; Groq is used only when a reviewer explicitly requests an
advisory reanalysis.

## Why Groq

ReconX defaults to Groq's `openai/gpt-oss-20b` model because Groq currently provides a
free-plan quota and this model supports strict JSON Schema structured output. The adapter
uses that constrained output, a five-second application deadline, a response-size limit,
one retry, a circuit breaker and the existing deterministic fallback. GPT-OSS requests
use Groq's documented low reasoning effort, hidden reasoning and single-user-message
prompt shape for reliable schema generation.

Gemini's free tier was not selected because Google's pricing page says free-tier content
may be used to improve its products. OpenRouter's free models are useful for experiments,
but its documented 50-request daily limit is a weaker fit for a live judging demo.

Official references:

- <https://console.groq.com/docs/rate-limits>
- <https://console.groq.com/docs/structured-outputs>
- <https://console.groq.com/docs/your-data>
- <https://ai.google.dev/gemini-api/docs/pricing>
- <https://openrouter.ai/docs/faq>

Use only synthetic data and Razorpay Test Mode data in this free deployment. Before any
real finance data is considered, complete provider, privacy, retention, regional and
organisational compliance reviews. Groq says inference inputs and outputs are not retained
by default, although limited temporary logging can occur; enable Zero Data Retention in
Groq Data Controls when the account is eligible.

## 1. Create the Groq key

1. Sign in at <https://console.groq.com/keys>.
2. Create a key for this buildathon project.
3. Save it in a password manager and in the local ignored `.env` as `GROQ_API_KEY`.
4. Set `LLM_PROVIDER=groq` and `ENABLE_LLM=true` locally.
5. Never paste the key into chat or commit it.

The checked-in `.env.example` contains every non-secret setting. Your local `.env` is
ignored by Git and is never uploaded to Render automatically.

## 2. Deploy the Blueprint

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/23241a6749/ReconX)

The root `render.yaml` creates one free Docker web service in Singapore and asks for these
three secrets during the initial Blueprint flow:

- `GROQ_API_KEY`
- `RAZORPAY_KEY_ID` from Razorpay Test Mode
- `RAZORPAY_KEY_SECRET` from Razorpay Test Mode

Enter them directly in Render's secret fields. Do not add them to `render.yaml`, GitHub,
screenshots, issue text or chat. The Blueprint generates an independent webhook secret;
it does not reuse the Razorpay API secret.

Render supplies `PORT`, and the container binds to it on `0.0.0.0`. The service exposes
`GET /health` for deployment health checks. Automatic deployment waits for the linked
branch's checks to pass.

## 3. Verify the live service

After Render reports a successful deploy:

1. Open `https://YOUR-SERVICE.onrender.com/health` and confirm `status` is `ok`.
2. Open the service root and run the held-out reconciliation demo.
3. Open a review case and request reanalysis. The UI should report
   `groq_chat_completions`; if the free quota or provider is unavailable, it will show the
   deterministic fallback instead.
4. Import only the included synthetic fixture triplet first.
5. When ready, use the guarded live-import endpoint only with a Test Mode date.

## Free-hosting limitation

Render's free web services spin down after 15 idle minutes and have an ephemeral
filesystem. Review decisions and webhook delivery history stored in SQLite can therefore
reset after a spin-down, restart or redeploy. The seeded review queue is rebuilt on start,
so this is suitable for a buildathon demonstration but is not production persistence.
Render documents that free Postgres also expires after 30 days. A production version
must move the review and webhook repositories to durable managed storage.

Official Render references:

- <https://render.com/docs/blueprint-spec>
- <https://render.com/docs/free>
- <https://render.com/docs/web-services>
