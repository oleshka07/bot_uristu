# PR-mode & branch protection (you stay in control)

By default I push straight to the working branch and it auto-deploys. If you'd
rather review every change before it ships, switch to **PR-mode**: I open Pull
Requests, you read the diff and click **Merge**, and only then does it deploy.

This keeps a human gate on a production system that sits next to Chater and your
real client data — without slowing day-to-day work much.

---

## How it works
- I do all work on feature branches (e.g. `feature/...`) and open a PR into the
  protected branch.
- You review the diff on GitHub and merge when happy.
- The deploy workflow runs **on merge** to the protected branch.

The PR template (`.github/pull_request_template.md`) prompts for what changed,
how it was tested, and rollback notes.

---

## Enable branch protection (one-time, ~2 min)
GitHub → repo **Settings → Branches → Add branch ruleset** (or *Add rule*):

1. **Target branch**: your deploy branch
   (`claude/networking-ai-contact-service-o73dse`, or `main` if you make that
   the deploy branch).
2. Enable:
   - ☑ **Require a pull request before merging**
     (set *Required approvals* = 1 if you want to force a click; as the repo
     owner you can approve & merge your own PRs).
   - ☑ **Require status checks to pass** (optional — only if/when CI tests run).
   - ☑ **Do not allow bypassing the above settings** (optional, stricter).
3. Save.

After this, direct pushes to that branch are blocked; everything comes via PRs.

> Tip: keep auto-deploy triggering on the **protected branch only**, so nothing
> ships until a PR is merged. The current `deploy.yml` already deploys on push
> to that branch — once protection is on, "push" only happens through merges.

---

## Make the deploy gate match
If you adopt `main` as the protected, deploy branch:
1. Merge the working branch into `main`.
2. In `.github/workflows/deploy.yml`, keep `main` under `on: push: branches:`.
3. Protect `main` per the steps above.

Tell me which branch you want as the deploy target and I'll align the workflow.

---

## Switching me to PR-mode
Just say **"work in PR-mode"**. From then on I will:
- never push directly to the protected branch,
- open a PR per change with a filled-in template,
- wait for your merge before considering it shipped.

You can switch back anytime with **"push directly is fine"**.
