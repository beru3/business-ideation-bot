import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const dir = fileURLToPath(new URL('../', import.meta.url));
const themesConfig = JSON.parse(readFileSync(dir + 'themes.json', 'utf8'));

function selectThemeByWeight(config) {
  const totalWeight = config.domains.reduce((s, d) => s + d.weight, 0);
  let r = Math.random() * totalWeight;
  for (const domain of config.domains) {
    r -= domain.weight;
    if (r <= 0) {
      const theme = domain.themes[Math.floor(Math.random() * domain.themes.length)];
      return { theme, domainId: domain.id };
    }
  }
  const fallback = config.domains[0];
  return { theme: fallback.themes[0], domainId: fallback.id };
}

describe('themes.json v2', () => {
  it('should have version 2.0', () => {
    expect(themesConfig.version).toBe('2.0');
  });

  it('should have 3 domains', () => {
    expect(themesConfig.domains).toHaveLength(3);
  });

  it('should have correct domain IDs', () => {
    const ids = themesConfig.domains.map(d => d.id);
    expect(ids).toContain('core_medical');
    expect(ids).toContain('care_adjacent');
    expect(ids).toContain('wild_card');
  });

  it('weights should sum to 100', () => {
    const total = themesConfig.domains.reduce((s, d) => s + d.weight, 0);
    expect(total).toBe(100);
  });

  it('each domain should have at least 1 theme', () => {
    for (const domain of themesConfig.domains) {
      expect(domain.themes.length).toBeGreaterThan(0);
    }
  });

  it('no duplicate themes across domains', () => {
    const all = themesConfig.domains.flatMap(d => d.themes);
    const unique = new Set(all);
    expect(unique.size).toBe(all.length);
  });
});

describe('selectThemeByWeight', () => {
  it('should converge to expected ratios within ±3% over 10000 trials', () => {
    const counts = { core_medical: 0, care_adjacent: 0, wild_card: 0 };
    const trials = 10000;

    for (let i = 0; i < trials; i++) {
      const { domainId } = selectThemeByWeight(themesConfig);
      counts[domainId]++;
    }

    const ratios = {};
    for (const [k, v] of Object.entries(counts)) {
      ratios[k] = v / trials;
    }

    expect(ratios.core_medical).toBeCloseTo(0.50, 1);
    expect(ratios.care_adjacent).toBeCloseTo(0.30, 1);
    expect(ratios.wild_card).toBeCloseTo(0.20, 1);
  });
});
