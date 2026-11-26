# Bird alerts

Sends a notification to your phone when an owl, a raptor, or a bird eBird marks as rare is reported within 2 miles of you. Checks every 15 minutes for birds seen in the last 2 hours.

## Setup (about 10 minutes)

1. **Get an eBird API key.** Sign in at https://ebird.org/api/keygen (free eBird account) and copy the key.

2. **Set up phone notifications.** Install the **ntfy** app (iOS or Android). Tap **+** and subscribe to a topic with a long random name nobody would guess, like `isaiah-birds-7f3k9q2m`. Anyone who knows the name can see your alerts, so keep it hard to guess.

3. **Make a GitHub repo.** Create a repository called `bird-alerts` and upload all the files from this folder, including the `.github` folder. Make it public to run every 15 minutes for free. Your location and keys go in secrets, which stay hidden either way.

4. **Add your secrets.** In the repo go to **Settings > Secrets and variables > Actions > New repository secret** and add:

   | Name | Value |
   |---|---|
   | `EBIRD_API_KEY` | your eBird key |
   | `NTFY_TOPIC` | the topic name from step 2 |
   | `HOME_LAT` | your latitude |
   | `HOME_LNG` | your longitude |

   Optional: under the **Variables** tab, add `RADIUS_MILES` to change the 2 mile default.

5. **Turn it on.** Go to the **Actions** tab, enable workflows if asked, open **Bird alerts**, and click **Run workflow** to test it. You should get alerts for anything from the last 2 days, then only new sightings after that.

## Good to know

- eBird hides the exact location of some sensitive species, which includes some owls, so not every owl report will come through.
- Alerts marked "Not yet confirmed" are fresh reports a reviewer hasn't checked yet.
- GitHub sometimes runs scheduled jobs a few minutes late.
- If the repo has no activity for 60 days, GitHub may pause the schedule and email you. One click in the Actions tab turns it back on.
- Running every 15 minutes needs a public repo to stay free. Your location and keys stay hidden in secrets, and seen.json stores scrambled IDs only.
