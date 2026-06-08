/** Google APIs return all-day values as `YYYY-MM-DD` and timed values as full ISO datetimes. */
export function formatDate(value: string): string {
  const date = new Date(value);
  return value.length > 10
    ? date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
    : date.toLocaleDateString(undefined, { dateStyle: "medium" });
}
