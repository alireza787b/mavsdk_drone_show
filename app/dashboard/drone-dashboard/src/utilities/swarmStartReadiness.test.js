import { swarmStartReadiness } from './swarmStartReadiness';
test('only fresh identity-matching node decisions enable the selected roles', () => {
  const d = { '1': { hw_id:'1',status:'ready',valid_for_ms:1000 } };
  expect(swarmStartReadiness(['1'], d, 1000, 1).ready).toBe(true);
  expect(swarmStartReadiness(['1'], d, 1000, 1000).ready).toBe(false);
  expect(swarmStartReadiness(['1','2'], d, 1000, 1).ready).toBe(false);
  expect(swarmStartReadiness(['2'], { '2': d['1'] }, 1000, 1).ready).toBe(false);
});
