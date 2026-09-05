/* Golden V2 browser vectors shared with tests/fixtures/v2/portfolio_hand_cases.json. */
self.WbaPortfolioGolden = {
  ledger_perfect_hedge: { losses: [10, 20, 40], payoffs: [[0], [10], [30]], weights: [0.25, 0.5, 0.25], positions: [1], fixed_cost: 2, residual_loss: [12, 12, 12] },
  weighted_tail: { losses: [0, 10, 100], weights: [0.9, 0.05, 0.05], es90: 55, es95: 100 },
  payoff_identity: { index: [5, 10, 15], strike: 10, call: [0, 0, 5], put: [5, 0, 0] },
};
