"use client";

// The first step of a new client: a company's year-end accounts, or an individual's Self Assessment return.
import { Modal } from "@/components/ui/dialog";
import { CompanyPicture, IndividualPicture } from "@/components/sa/Illustrations";

interface WhoForChooserProps {
  isOpen: boolean;
  onClose: () => void;
  onCompany: () => void;
  onIndividual: () => void;
}

const CARDS = [
  { key: "company", title: "Company", line: "Accounts, corporation tax and the workbook", Picture: CompanyPicture },
  { key: "individual", title: "Individual", line: "Personal tax return: employment, self-employment, property and more",
    Picture: IndividualPicture },
] as const;

export function WhoForChooser({ isOpen, onClose, onCompany, onIndividual }: WhoForChooserProps) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Who is this for?"
           description="A company's year-end accounts, or a person's Self Assessment return.">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-4">
        {CARDS.map(({ key, title, line, Picture }) => (
          <button
            key={key}
            type="button"
            onClick={key === "company" ? onCompany : onIndividual}
            className="group flex flex-col justify-start text-left rounded-2xl border border-slate-200 bg-white p-4 transition-all hover:border-teal-400 hover:bg-teal-50/50 hover:shadow-md cursor-pointer"
          >
            <div className="rounded-xl bg-teal-50 group-hover:bg-white transition-colors p-3">
              <Picture className="w-full h-32" />
            </div>
            <h3 className="mt-3 text-sm font-bold text-slate-900">{title}</h3>
            <p className="mt-0.5 text-xs text-slate-500">{line}</p>
          </button>
        ))}
      </div>
    </Modal>
  );
}
