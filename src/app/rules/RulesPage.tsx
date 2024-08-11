import { LeagueScheduleTable } from "./LeagueScheduleTable";

export const RulesPage = () => {
  return (
    <div className="container mx-auto px-4 py-8">
      <h1 className="mb-6 text-4xl font-bold">
        Guillotine Gulag League Rules and Schedule
      </h1>

      <section className="mb-8">
        <h2 className="mb-4 text-3xl font-semibold">Concept</h2>
        <p className="mb-4">
          Welcome to the ultimate fantasy football experience - the Guillotine
          Gulag League! This 19-20 team Battle Royale will test your skills,
          strategy, and survival instincts. Here's what you need to know:
        </p>
        <ul className="mb-4 list-disc pl-6">
          <li>
            <strong>Battle Royale Format</strong>: Each week, the bottom 2 teams
            are sent to the gulag to fight for survival.
          </li>
          <li>
            <strong>Elimination</strong>: After the gulag closes, the bottom
            team is dropped from the league.
          </li>
          <li>
            <strong>Buy-in</strong>: $50 entry fee - winner takes all!
          </li>
          <li>
            <strong>Creative Survival</strong>: Use any strategy you can imagine
            to survive, but avoid collusion at all costs.
          </li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="mb-4 text-3xl font-semibold">General Roster Rules</h2>
        <ol className="mb-4 list-decimal pl-6">
          <li>
            <strong>Team Size</strong>: Maintain exactly 9 players on your
            roster at all times.
          </li>
          <li>
            <strong>Starting Lineup</strong>: You don't have to start all your
            players.
          </li>
          <li>
            <strong>Player Lock</strong>: Players are locked at their scheduled
            game time in the app.
          </li>
          <li>
            <strong>Weekly Bonus</strong>: Win your head-to-head matchup to earn
            an extra $5 (includes gulag/gladiator teams).
          </li>
        </ol>
      </section>

      <section className="mb-8">
        <h2 className="mb-4 text-3xl font-semibold">Gulag & Gladiator Rules</h2>
        <ul className="mb-4 list-disc pl-6">
          <li>
            <strong>Bottom 2 Teams</strong>: Lose all players except 2 nominated
            keepers.
          </li>
          <li>
            <strong>Champion Substitution</strong>: Pay someone to take your
            place, but both take the gulag penalty.
          </li>
          <li>
            <strong>Rebuilding</strong>: Rebuild teams through waivers or trades
            during the gulag week.
          </li>
          <li>
            <strong>Gulag Showdown</strong>: Separate head-to-head faceoff, not
            the in-app matchup.
          </li>
          <li>
            <strong>Gladiator Bonus</strong>: Gladiator wins are rewarded with 1
            keeper.
          </li>
          <li>
            <strong>Elimination</strong>: Loser is dropped from the league.
          </li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="mb-4 text-3xl font-semibold">Auction Draft Rules</h2>
        <ul className="mb-4 list-disc pl-6">
          <li>
            <strong>No Auto-drafters</strong>: Auto-drafting without permission
            results in first-week gulag placement.
          </li>
          <li>
            <strong>Budget</strong>: Start with a $200 budget.
          </li>
          <li>
            <strong>FAAB Conversion</strong>: Unspent auction dollars convert to
            FAAB at a 5:1 ratio.
          </li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="mb-4 text-3xl font-semibold">Waiver Rules</h2>
        <ul className="mb-4 list-disc pl-6">
          <li>
            <strong>First FAAB Bids</strong>: Clear on Thursday morning at 2AM
            CST.
          </li>
          <li>
            <strong>Second Bidding Window</strong>: Clears on Saturdays at 11AM
            CST.
          </li>
          <li>
            <strong>Player Locks</strong>: Played or locked players cannot be
            moved.
          </li>
          <li>
            <strong>Waiver Bugs</strong>: Commissioner will handle through
            silent auctions if necessary.
          </li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="mb-4 text-3xl font-semibold">Trading Rules</h2>
        <ul className="mb-4 list-disc pl-6">
          <li>
            <strong>Approval Process</strong>: Trades must be submitted in
            writing and approved by the commissioner.
          </li>
          <li>
            <strong>Creativity Encouraged</strong>: Almost anything is allowed
            that isn't collusion.
          </li>
          <li>
            <strong>Veto Power</strong>: Commissioner reserves the right to veto
            unfair trades.
          </li>
          <li>
            <strong>Prohibited Trades</strong>: No roster spot trading to hurt
            others, player renting at large discounts, or real-life favors for
            fantasy gain.
          </li>
          <li>
            <strong>Allowed Creative Trades</strong>: Player rentals, options on
            player ownership, brokering trades, and more.
          </li>
        </ul>
      </section>

      <section className="mb-8">
        <h2 className="mb-4 text-3xl font-semibold">
          2024-2025 League Schedule
        </h2>
        <div className="overflow-x-auto">
          <LeagueScheduleTable />
        </div>
      </section>
    </div>
  );
};
