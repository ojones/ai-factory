export function median(nums: number[]): number {
  const sorted = nums.sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}
