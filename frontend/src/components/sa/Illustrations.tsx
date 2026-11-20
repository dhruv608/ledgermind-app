// unDraw illustrations (undraw.co, free to use), recoloured to the app's teal and kept in public/illustrations:
// "Business plan" for a company, "Budgeting" for an individual.

export function CompanyPicture({ className = "" }: { className?: string }) {
  // eslint-disable-next-line @next/next/no-img-element
  return <img src="/illustrations/company.svg" alt="" className={`object-contain ${className}`} />;
}

export function IndividualPicture({ className = "" }: { className?: string }) {
  // eslint-disable-next-line @next/next/no-img-element
  return <img src="/illustrations/individual.svg" alt="" className={`object-contain ${className}`} />;
}
