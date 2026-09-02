# Owner setup checklist

This document lists only the items that must come from the repository owner. Never send
passwords, one-time codes, GitHub tokens, Razorpay API secrets or webhook secrets in chat.

## 1. Confirm three application details

Send these as plain text:

1. College name exactly as it should appear in the application.
2. Application/contact email address.
3. Preferred internship duration: 6 months or 12 months.
If you publish from your own computer rather than through the connected GitHub workflow,
you will also need a Git commit email. This may be your public GitHub email or
GitHub-provided no-reply address; it is not a password.

To find the GitHub no-reply address:

1. Sign in to GitHub.
2. Click the profile picture → **Settings**.
3. Open **Emails**.
4. Enable **Keep my email addresses private** if desired.
5. Copy the no-reply address GitHub displays for command-line operations.

## 2. Prepare the public GitHub repository

Recommended repository: `23241a6749/ReconX`.

1. Open <https://github.com/new> while signed in.
2. Set **Owner** to `23241a6749`.
3. Enter repository name `ReconX`.
4. Add description: `Evidence-first AI finance controller for Razorpay settlement reconciliation.`
5. Select **Public** because the Buildathon explicitly asks for a public repository.
6. Do not initialise with README, `.gitignore` or license; these already exist locally.
7. Click **Create repository**.
8. Copy the HTTPS repository URL and send only that URL. Do not send a token.
9. Explicitly confirm whether the verified ReconX source may be published to that public
   repository. If the GitHub connection is authorised, the remaining files can be
   committed without sharing your password or token.

For authentication on your Windows laptop, prefer GitHub Desktop or GitHub CLI browser
login instead of pasting a personal access token into chat. If using GitHub CLI:

1. Install GitHub CLI from <https://cli.github.com/>.
2. Open PowerShell and run `gh auth login`.
3. Choose `GitHub.com`, `HTTPS`, and browser authentication.
4. Complete the browser approval in your own browser.
5. Run `gh auth status`; it should show `23241a6749`.

## 3. Create Razorpay Test Mode credentials

Only Test Mode is needed. Razorpay documents it as a simulation in which customers cannot
make real payments.

1. Sign in to <https://dashboard.razorpay.com/>.
2. Switch the Dashboard mode to **Test**.
3. Open **Account & Settings**.
4. Under **Website and app settings**, open **API Keys**.
5. Click **Generate Key**.
6. Download/save the key once in a password manager or local `.env` file.
7. Never commit it. The key secret is not shown again; regenerate it if lost.
8. On your own machine, copy `.env.example` to `.env` and set `RAZORPAY_KEY_ID` and
   `RAZORPAY_KEY_SECRET`. The `.env` file is already ignored by Git.

Official guide: <https://razorpay.com/docs/payments/dashboard/account-settings/api-keys/>

## 4. Configure the Test Mode webhook after deployment

You need a deployed public HTTPS URL first; localhost is not accepted directly.

1. In Razorpay Test Mode, open **Account & Settings → Webhooks**.
2. Click **Add New Webhook**.
3. Enter `https://YOUR-DEPLOYED-HOST/api/webhooks/razorpay`.
4. Generate a new random webhook secret in a password manager. Do not reuse the API key
   secret and do not send this value in chat.
5. Add an alert email you actively monitor.
6. Select only `payment.captured`, `refund.processed` and `settlement.processed`.
7. Click **Create Webhook**. Razorpay’s documentation states that Test Mode may use the
   default OTP `754081` when prompted.
8. Store the same webhook secret in the deployment platform as
   `RAZORPAY_WEBHOOK_SECRET`.
9. Trigger Test Mode transactions, then confirm the webhook endpoint returns 2xx and the
   integration dashboard shows deliveries without duplicates.

Official guides:

- <https://razorpay.com/docs/webhooks/setup-edit-payments>
- <https://razorpay.com/docs/webhooks/validate-test/>

## 5. Record and publish the pitch video

1. Follow `docs/demo-script.md` and record at 1080p landscape.
2. Keep the finished video at or below five minutes.
3. Upload it to YouTube as **Unlisted**, or Google Drive with **Anyone with the link —
   Viewer** access.
4. Open the link in an incognito/signed-out browser.
5. Confirm video and audio play without requesting access.
6. Send the public-viewable URL, not the video-account password.

## 6. Final form submission

1. Open <https://forms.gle/d9r2gvxp8cmoZhon9>.
2. Use the reviewed answers in `docs/submission.md`.
3. Reopen the GitHub and video links in signed-out windows.
4. Verify the public repository’s Actions tab is green on the submitted commit.
5. Select the final-confirmation checkbox only after every field is checked.
6. Submit before the official 5 September deadline and save the confirmation receipt.
