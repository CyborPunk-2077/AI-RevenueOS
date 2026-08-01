/**
 * Committed on purpose.
 *
 * Without an ESLint config, `next lint` asks an interactive setup question and
 * waits for an answer, so `turbo run lint` hung rather than failing — the worst
 * possible behaviour in CI or in a launcher.
 *
 * This is `.eslintrc.js` rather than `.eslintrc.json` because JSON has no
 * comments and ESLint rejects a `"//"` key outright.
 */
module.exports = {
  root: true,
  extends: ['next/core-web-vitals'],
  rules: {
    // `console.error` is how the BFF surfaces an upstream failure the operator
    // has to see, so warn/error stay allowed and stray debugging does not.
    'no-console': ['error', { allow: ['warn', 'error'] }],
    eqeqeq: ['error', 'smart'],
    'no-var': 'error',
    'prefer-const': 'error',
  },
  ignorePatterns: ['.next/**', 'node_modules/**', 'next-env.d.ts', 'coverage/**'],
};
