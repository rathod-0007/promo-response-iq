# RxLift demo video

`RxLift_demo.mp4` (3 min 12 s, 1280x720, about 3.5 MB) is a screen recording of the finished project running on the sample prescriber extract. Click the file on GitHub to play it, or download it for presenting offline.

| Time | What you see |
|---|---|
| 0:00 | Title |
| 0:07 | **1. The web app**: Overview, Response model, Optimizer, Targeting, Incentive comp, Prescriber explorer (search), Data & reports, BI connections |
| 1:09 | **2. Tableau**: the 9 worksheets (Rx by month, Detail visits by month, Rx by state, segment and specialty, ROI by channel, Call index by decile, Attainment and Payout by territory) and the 2 dashboards |
| 2:22 | **3. Power BI**: the Performance, Where to focus and Incentive plan pages, the model view (relationships) and the data view |

## Talking points for a demo

* One PostgreSQL star schema feeds the web app, the Excel and PowerPoint exports, Tableau and Power BI, so every tool shows the same numbers (for example 57,405 prescriptions in all three).
* The Tableau and Power BI files are generated, so they rebuild for any uploaded data set and use that data set's own wording.
* The model, optimizer, targeting and incentive plan are in the web app; Tableau and Power BI are the client-facing views.

## Re-recording

The video was recorded from the real applications (Tableau Public, Power BI Desktop and the browser). To record again, follow the README to open the three, then record the screen with any recorder.
