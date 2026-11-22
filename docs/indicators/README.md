# Indicator conventions

These rules apply to **every** JANICE quality improvement (QI) indicator. They are clinical and methodological choices, so the **indicator review group** signs them off once, not again for each indicator. That group is the CIN clinical lead for each unit, a QI lead from a pilot hospital and a CIN data manager.

- Each indicator's own definition is in the [indicator catalogue](catalogue.md).
- **Status: draft**, awaiting review-group sign-off. When the group approves, record the date and names at the end of this page.

## How each indicator is defined

- **Defined once, next to its code.** An indicator's definition lives in its dbt model's YAML (`pipeline/dbt/models/qi/…`). The pages in this folder are generated from that YAML (`uv run janice-indicators`), and a test fails if they fall out of date. To change a definition, change the YAML in a pull request, raise its version, and get it re-approved.
- **Versioned.** A change to a numerator, denominator or exclusion is a new version (1.0 becomes 1.1, or 2.0 if results are no longer comparable). Reports state the version they used.

## Counting

1. **One row per site per month.** Each indicator table counts the patients of one hospital in one admission month. Wider views (county, network, a quarter) are built by adding counts and then dividing, never by averaging rates.
2. **The month is the admission month.** Admissions without a usable admission date cannot be placed in a month. They are left out, and the staging tests report how many.
3. **Every rate is reported with its numerator and denominator,** so a reader can always see how many patients it rests on.

## Missing, unknown and implausible data

4. **CIN's "not recorded" codes are treated as missing,** never as values: `-1` for numbers and codes, `1914-01-01` for dates. An empty temperature is not −1 °C.
5. **When the indicator asks "how many had X?" (a measurement), a patient without that measurement leaves the denominator.** For example, hypothermia counts only babies whose temperature was recorded. The share without a measurement is reported as documentation completeness.
6. **When the indicator asks "was X done?" (care), not documented counts as not done.** This is the usual clinical audit rule. For example, KMC not recorded counts as not given. Documentation completeness shows how much of the rate rests on unanswered questions.
7. **Implausible values are left out of rates, but counted.** For example, a temperature outside 25–43 °C, or a birth weight under 300 g or over 6000 g, is almost certainly a typing error, and would otherwise report harm that never happened. Each such value is counted in its own column, and the data managers get a list to correct in REDCap.
8. **An unknown outcome is not treated as survival.** Referred, absconded and discharged-against-advice patients are left out of case fatality and reported next to it.
9. **No denominator, no rate.** When nobody is eligible in a month, the rate is empty, not 0%, so it can never read as perfect care.

## Data quality

10. **Every indicator reports its documentation completeness** next to its rate, so a fall in performance can be told apart from a fall in recording.
11. **Fields that the form never shows are never used.** Some CIN form fields have branching logic that can never be true, so REDCap never displays them. No indicator may use these fields, and a test warns if one starts receiving data.
12. **Full-form records only, where the form requires it.** Some fields appear only on full-form records (`[is_minimum] = '0'`). Indicators using them count only full-form records, so minimum records do not read as "not done".

## Sharing results

13. **Small numbers are suppressed before results reach any user.** The indicator tables keep exact counts, for validation against CIN's own reports. The query service suppresses cells below the agreed threshold, which is configurable and set by data governance.
14. **Comparisons between hospitals need governance approval** (Gate 3). Until then, users see their own hospital's results.

## Sign-off

| Date | Approved by | Version of these conventions |
| --- | --- | --- |
| | | |
