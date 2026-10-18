/** The admin wordmark: the product name with an "Admin" badge, so admins know where they are. */
export function Brand() {
  return (
    <p className="brand">
      <img src="/favicon.svg" alt="" width={24} height={24} />
      <span className="brand__name">Strong Hire</span>
      <span className="badge badge--admin">Admin</span>
    </p>
  );
}
