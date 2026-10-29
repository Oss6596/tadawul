# Almujalli Family Game · لعبة عائلة المجلي

Live: https://oss6596.github.io/tadawul/

A family brain-games app for iPad, iPhone and Android. Everyone plays the same five games at their own level,
so a 6-year-old, an 11-year-old and the adults can compete fairly for the cup.

| Level | Ages | Example challenges |
|---|---|---|
| Little Star | 5–8 | Count the apples, 3 + 4 with pictures, CAT 🐱, 🔴🔵🔴🔵 ? |
| Explorer | 9–14 | 8 × 7, 84 ÷ 7, PLANET, 4, 9, 16, 25, ? |
| Master | 15+ | 23 × 17, 75% of 180, LABYRINTH, primes, Fibonacci, letter skips |

**Games:** Number Sprint, Memory Match, Word Builder, What Comes Next?, Sharp Eyes.
Each turn scores up to 100 points, with bonus points for speed.

**Modes**

* **Family cup**: 3, 5 or 7 rounds. Pass the device between players, see the scoreboard after each round, and finish on a podium.
* **Play online**: everyone plays on their own phone or iPad, wherever they are. One person taps **Create a room**
  and sends the 5-letter code (or the join link) to the others, who tap **Join**. Each round everyone plays the same game
  at their own level at the same time, and all devices show the scoreboard and the final podium.
  Devices connect directly to each other (WebRTC, using the bundled [PeerJS](https://peerjs.com) library and its free
  connection and relay servers), so there is no server to run or pay for. Scores never leave the players' devices except to
  reach the other players in the room.
* **Practice**: one player, one game, tracking personal bests.
* **Hall of fame**: cups won and each player's best score in every game.

**English and Arabic.** Tap **ع** / **EN** on the home screen to switch. Arabic mode has a full right-to-left layout,
Arabic word lists for every level (قطة 🐱, كوكب, خوارزمية …), the Arabic alphabet in letter patterns and Arabic-Indic digits (١٢٣).
The game starts in Arabic on devices set to Arabic.

Players (name, age, animal avatar) and scores are saved on the device.

It is a plain web app (HTML + JavaScript, no build step). Everything except online play works offline once it has been opened,
and it can be installed to the home screen like a normal app.

## Try it locally

```bash
cd family-game
python3 -m http.server 8000
# open http://localhost:8000 on this computer,
# or http://<your-computer-ip>:8000 from an iPad/phone on the same Wi-Fi
```

Offline mode and "Install" only work over HTTPS, so test those on the published link.

---

## Publish it as a link

Pick one option. Each gives you an `https://` link to send to your family.

### Option A: Cloudflare Pages (automatic, free)

This repo already deploys to Cloudflare, so the workflow `.github/workflows/family-game.yml` publishes the game
whenever `family-game/` changes on `main`.

1. Cloudflare dashboard → **My Profile → API Tokens** → edit the token stored in the `CLOUDFLARE_API_TOKEN` secret,
   and add the permission **Account → Cloudflare Pages → Edit**.
2. Merge this branch into `main` (or run the workflow from the **Actions** tab → *Deploy Family Brain Cup* → *Run workflow*).
3. The game is live at **https://family-brain-cup.pages.dev**. The link is also shown on the workflow run summary.

### Option B: Netlify Drop (no accounts or settings, about 1 minute)

1. Download the `family-game` folder.
2. Open https://app.netlify.com/drop and drag the folder onto the page.
3. You get a link like `https://something.netlify.app`. Sign up (free) to keep it permanently and give it a nicer name.

### Option C: GitHub Pages

Put the contents of `family-game/` in a **public** repository, then go to **Settings → Pages → Deploy from a branch → main / root**.
The link will be `https://<your-username>.github.io/<repo>/`. GitHub Pages on private repositories needs a paid GitHub plan.

## Install it on the devices ("downloadable")

Open the link once on each device, then:

* **iPad / iPhone (Safari):** tap **Share** → **Add to Home Screen** → **Add**.
* **Android (Chrome):** tap **Install on this device** on the home screen of the game, or ⋮ → **Install app**.

It gets its own icon, opens full screen without the browser bar, and works without internet.
Each device keeps its own players and trophies.

**Updating:** after changing `index.html`, bump `VERSION` in `sw.js` (for example `almujalli-v4`) before publishing.
Devices pick up the new version the next time the game is opened twice.

## Optional: real App Store / Play Store apps

You do not need this for family use, because the home-screen install above is a full offline app. If you later want
store apps, wrap the same folder with [Capacitor](https://capacitorjs.com):

```bash
npm i @capacitor/core @capacitor/cli @capacitor/android @capacitor/ios
npx cap init "Almujalli Family Game" com.almujalli.familygame --web-dir family-game
npx cap add android && npx cap add ios
npx cap sync
npx cap open android   # Android Studio → Build → Build APK (install the APK on Android devices directly)
npx cap open ios       # Xcode on a Mac → run on your iPad with a free Apple ID (re-sign every 7 days)
```

Publishing to the stores costs $25 once (Google Play) and $99 per year (Apple Developer Program, which also gives you TestFlight).
