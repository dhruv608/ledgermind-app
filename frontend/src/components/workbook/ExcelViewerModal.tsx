import { useState, useEffect, useMemo } from "react";
import * as XLSX from "xlsx";
import {
  X,
  FileSpreadsheet,
  Download,
  Search,
  Maximize2,
  Minimize2,
  Loader2,
  Info,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CustomSelect } from "@/components/ui/custom-select";
import { plural } from "@/lib/formatters";
import { cellStyle, readLook, type SheetLook } from "./sheetStyles";

/** Rows of a sheet as the text Excel displays: a date stays 30/09/2025, not the serial number 45930. */
const readSheet = (ws: XLSX.WorkSheet): any[][] =>
  XLSX.utils.sheet_to_json(ws, { header: 1, defval: "", blankrows: true, raw: false });

// "1,234.50", "(200.00)", "-£5.00", "12%" all line up on the right like numbers
const looksNumeric = (v: string) => /^[-(]?£?-?[\d,]+(\.\d+)?\)?%?$/.test(v.trim());

interface ExcelViewerModalProps {
  isOpen: boolean;
  onClose: () => void;
  fileUrl?: string | null;
  fileBlob?: Blob | null;
  fileName?: string;
  /** Open on the first sheet whose name starts with this (e.g. "H1"); otherwise the first sheet. */
  initialSheet?: string | null;
}

export function ExcelViewerModal({
  isOpen,
  onClose,
  fileUrl,
  fileBlob,
  fileName = "Workpaper_Spreadsheet.xlsx",
  initialSheet = null,
}: ExcelViewerModalProps) {
  const [workbook, setWorkbook] = useState<XLSX.WorkBook | null>(null);
  const [sheetNames, setSheetNames] = useState<string[]>([]);
  const [activeSheet, setActiveSheet] = useState<string>("");
  const [sheetData, setSheetData] = useState<any[][]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [selectedCell, setSelectedCell] = useState<{ row: number; col: number; val: string } | null>(null);
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  // The workbook's own look (ExcelJS), when it could be read: per sheet, worked out the first time it is shown
  const [styled, setStyled] = useState<any | null>(null);
  const [looks, setLooks] = useState<Record<string, SheetLook>>({});
  const [tabColours, setTabColours] = useState<Record<string, string | null>>({});

  // Closing clears the workbook shown (set while rendering, not in the effect below)
  const [wasOpen, setWasOpen] = useState(isOpen);
  if (wasOpen !== isOpen) {
    setWasOpen(isOpen);
    if (!isOpen) {
      setWorkbook(null);
      setSheetNames([]);
      setActiveSheet("");
      setSheetData([]);
      setSelectedCell(null);
      setStyled(null);
      setLooks({});
    }
  }

  // Load workbook from URL or Blob
  useEffect(() => {
    if (!isOpen) return;

    const loadSpreadsheet = async () => {
      setIsLoading(true);
      setLoadError(null);
      try {
        let buffer: ArrayBuffer;
        if (fileBlob) {
          buffer = await fileBlob.arrayBuffer();
        } else if (fileUrl) {
          const res = await fetch(fileUrl, { credentials: "include" });
          if (!res.ok) throw new Error("The workbook could not be downloaded.");
          buffer = await res.arrayBuffer();
        } else {
          throw new Error("No workbook to show.");
        }

        const wb = XLSX.read(buffer, { type: "array", cellFormula: true, cellStyles: true });
        // The look (fills, fonts, borders, widths, merges, frozen rows, tab colours) from the file itself; the plain
        // view when it cannot be read
        try {
          const ExcelJS: any = (await import("exceljs")).default;
          const book = new ExcelJS.Workbook();
          await book.xlsx.load(buffer.slice(0));
          setStyled(book);
          setLooks({});
          const colours: Record<string, string | null> = {};
          book.worksheets.forEach((w: any) => {
            const argb = w.properties?.tabColor?.argb;
            colours[w.name] = argb ? `#${String(argb).slice(-6)}` : null;
          });
          setTabColours(colours);
        } catch (e) {
          console.warn("Workbook look not read; plain preview", e);
          setStyled(null);
        }
        setWorkbook(wb);
        setSheetNames(wb.SheetNames);
        if (wb.SheetNames.length > 0) {
          const wanted = initialSheet ? initialSheet.toUpperCase() : "";
          const firstSheet = (wanted && wb.SheetNames.find((n) => n.toUpperCase().startsWith(wanted))) || wb.SheetNames[0];
          setActiveSheet(firstSheet);
          setSheetData(readSheet(wb.Sheets[firstSheet]));
        }
      } catch (err: any) {
        console.error("Failed to parse Excel:", err);
        setLoadError(err.message || "The workbook could not be read.");
      } finally {
        setIsLoading(false);
      }
    };

    loadSpreadsheet();
  }, [isOpen, fileUrl, fileBlob, initialSheet]);

  // Handle Sheet Tab Switch
  const handleSheetChange = (name: string) => {
    if (!workbook || !workbook.Sheets[name]) return;
    setActiveSheet(name);
    setSelectedCell(null);
    setSearchTerm("");
    setSheetData(readSheet(workbook.Sheets[name]));
  };

  const look: SheetLook | null = useMemo(() => {
    if (!styled || !activeSheet) return null;
    if (looks[activeSheet]) return looks[activeSheet];
    const ws = styled.getWorksheet(activeSheet);
    return ws ? readLook(ws) : null;
  }, [styled, activeSheet, looks]);
  // The look worked out is kept for the sheet (set while rendering: next time it is read from looks)
  if (look && activeSheet && !looks[activeSheet]) setLooks((prev) => ({ ...prev, [activeSheet]: look }));

  // The text a cell shows, by A1 reference (for the conditional rules)
  const textAt = (ref: string) => {
    const m = /^([A-Z]{1,3})(\d+)$/.exec(ref);
    if (!m) return "";
    const col = m[1].split("").reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0) - 1;
    const v = sheetData[Number(m[2]) - 1]?.[col];
    return v === undefined || v === null ? "" : String(v);
  };

  // Convert Column Index to Excel Letter (0 -> A, 1 -> B, 26 -> AA)
  const getColLetter = (index: number) => {
    let letter = "";
    while (index >= 0) {
      letter = String.fromCharCode((index % 26) + 65) + letter;
      index = Math.floor(index / 26) - 1;
    }
    return letter;
  };

  // Filtered rows based on search
  const filteredData = useMemo(() => {
    const all = sheetData.map((row, i) => ({ row, at: i }));
    if (!searchTerm.trim()) return all;
    const q = searchTerm.toLowerCase().trim();
    return all.filter(({ row }) => row.some((cell) => String(cell).toLowerCase().includes(q)));
  }, [sheetData, searchTerm]);
  const searching = Boolean(searchTerm.trim());

  // Max columns to render in grid
  const maxCols = useMemo(() => {
    let max = 0;
    sheetData.slice(0, 100).forEach((r) => {
      if (r.length > max) max = r.length;
    });
    return Math.max(max, 10);
  }, [sheetData]);
  const ROW_H = 24, HEAD_H = 26;


  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/80 backdrop-blur-xs flex items-center justify-center p-2 sm:p-4 animate-in fade-in duration-150">
      <div
        className={`bg-white rounded-2xl shadow-2xl flex flex-col border border-slate-200 overflow-hidden transition-all duration-200 ${
          isFullscreen ? "w-full h-full rounded-none" : "w-full max-w-6xl h-[88vh]"
        }`}
      >
        {/* Top Header Bar */}
        <div className="px-4 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between gap-3 shrink-0">
          <div className="flex items-center space-x-2.5 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-emerald-100 flex items-center justify-center shrink-0">
              <FileSpreadsheet className="w-4 h-4 text-emerald-700" />
            </div>
            <div className="min-w-0">
              <h3 className="text-xs font-bold text-slate-900 truncate">
                {fileName}
              </h3>
              <p className="text-[11px] text-slate-500 truncate">
                {plural(sheetNames.length, "sheet")} · read-only preview
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            {sheetNames.length > 1 && (
              <CustomSelect
                value={activeSheet}
                onChange={(name) => handleSheetChange(String(name))}
                align="right"
                title="Go to sheet"
                buttonClassName="max-w-[11rem]"
                options={sheetNames.map((n) => ({ value: n, label: n }))}
              />
            )}
            {/* Search inside sheet */}
            <div className="relative w-48 sm:w-64 hidden md:block">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
              <Input
                type="text"
                placeholder="Find in this sheet"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-8 text-xs h-8 bg-white border-slate-200 rounded-lg"
              />
            </div>


            {/* Download xlsx */}
            {fileUrl && (
              <a
                href={fileUrl}
                download
                className="h-8 px-2.5 text-xs font-medium text-white bg-teal-700 hover:bg-teal-800 rounded-lg inline-flex items-center space-x-1 shadow-2xs transition"
              >
                <Download className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Download</span>
              </a>
            )}

            {/* Fullscreen Toggle */}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsFullscreen(!isFullscreen)}
              className="h-8 w-8 p-0 text-slate-500 hover:text-slate-900 rounded-lg cursor-pointer"
            >
              {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
            </Button>

            {/* Close Button */}
            <Button
              variant="ghost"
              size="sm"
              onClick={onClose}
              className="h-8 w-8 p-0 text-slate-500 hover:text-slate-900 rounded-lg cursor-pointer"
            >
              <X className="w-4 h-4" />
            </Button>
          </div>
        </div>

        {/* Excel Formula Bar */}
        <div className="px-3 py-1.5 border-b border-slate-200 bg-white flex items-center space-x-2 text-xs shrink-0">
          <div className="w-16 font-mono font-bold text-slate-600 bg-slate-100 px-2 py-0.5 rounded text-center border border-slate-200 text-[11px]">
            {selectedCell
              ? `${getColLetter(selectedCell.col)}${selectedCell.row + 1}`
              : "A1"}
          </div>
          <div className="text-slate-400 font-serif italic text-xs select-none">fx</div>
          <div className="flex-1 font-mono text-slate-800 truncate px-2 py-0.5 bg-slate-50 rounded border border-slate-100 text-xs">
            {selectedCell ? selectedCell.val : (sheetData[0]?.[0] || "")}
          </div>
        </div>

        {/* Spreadsheet Content Grid */}
        <div className="flex-1 overflow-auto bg-slate-100 relative">
          {isLoading ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/90">
              <Loader2 className="w-8 h-8 text-emerald-600 animate-spin mb-2" />
              <p className="text-xs font-semibold text-slate-700">Opening the workbook…</p>
            </div>
          ) : loadError ? (
            <div className="p-8 text-center bg-white h-full flex flex-col items-center justify-center">
              <Info className="w-10 h-10 text-rose-500 mb-2" />
              <h4 className="text-sm font-bold text-slate-800">The preview could not open</h4>
              <p className="text-xs text-slate-500 mt-1 max-w-md">{loadError}</p>
            </div>
          ) : filteredData.length === 0 ? (
            <div className="p-8 text-center bg-white h-full flex flex-col items-center justify-center">
              <Search className="w-8 h-8 text-slate-400 mb-2" />
              <h4 className="text-xs font-semibold text-slate-700">Nothing in this sheet matches</h4>
            </div>
          ) : (
            <div className="inline-block min-w-full align-middle">
              <table className="border-collapse text-xs bg-white min-w-full">
                {/* Column Headers (A, B, C...) */}
                <thead className="sticky top-0 z-20 bg-slate-100 border-b border-slate-300 select-none">
                  <tr>
                    <th className="w-10 px-2 py-1 text-center bg-slate-200 border-r border-slate-300 text-slate-500 font-sans text-[11px]">
                      #
                    </th>
                    {Array.from({ length: maxCols }).map((_, cIdx) => (
                      <th
                        key={cIdx}
                        style={look ? { width: look.widths[cIdx] ?? 70, minWidth: look.widths[cIdx] ?? 70 } : undefined}
                        className={`px-3 py-1 text-center font-sans font-semibold text-slate-600 border-r border-slate-300 text-[11px] ${look ? "" : "min-w-[100px]"}`}
                      >
                        {getColLetter(cIdx)}
                      </th>
                    ))}
                  </tr>
                </thead>

                {/* Table Data Rows */}
                <tbody className={look ? "" : "divide-y divide-slate-200"}>
                  {filteredData.map(({ row, at: rIdx }) => {
                    // Excel's frozen title rows stay in view while scrolling (not while searching: rows are hidden)
                    const frozen = Boolean(look && !searching && rIdx < look.frozenRows);
                    return (
                    <tr key={rIdx} className={look ? "" : "hover:bg-emerald-50/20"}
                        style={frozen ? { position: "sticky", top: HEAD_H + rIdx * ROW_H, zIndex: 15, height: ROW_H } : look ? { height: ROW_H } : undefined}>
                      {/* Row Number */}
                      <td className="sticky left-0 z-10 w-10 px-2 py-1 text-center bg-slate-100 border-r border-slate-300 text-slate-500 font-sans text-[11px] select-none">
                        {rIdx + 1}
                      </td>

                      {/* Row Cells */}
                      {Array.from({ length: maxCols }).map((_, cIdx) => {
                        const key = `${rIdx},${cIdx}`;
                        if (look && !searching && look.covered.has(key)) return null;     // inside a merged cell
                        const cellVal = row[cIdx] !== undefined && row[cIdx] !== null ? String(row[cIdx]) : "";
                        const isSelected = selectedCell?.row === rIdx && selectedCell?.col === cIdx;
                        const isNum = looksNumeric(cellVal);
                        const span = look && !searching ? look.spans.get(key) : undefined;
                        const css = look ? cellStyle(look, rIdx, cIdx, cellVal, textAt) : undefined;
                        const width = look?.widths[cIdx];
                        // Text runs on into the empty cells to its right, as in Excel (numbers stay in their cell)
                        const next = row[cIdx + 1];
                        const spill = Boolean(look && !isNum && cellVal && (next === undefined || next === null || next === "")
                                              && !css?.whiteSpace);
                        // As far as the next filled cell, as Excel does (it never writes over another cell's text)
                        let room = 0;
                        if (spill && look) {
                          for (let k = cIdx; k < maxCols; k++) {
                            if (k > cIdx && row[k] !== undefined && row[k] !== null && row[k] !== "") break;
                            room += look.widths[k] ?? 70;
                          }
                        }

                        return (
                          <td
                            key={cIdx}
                            colSpan={span?.cols}
                            rowSpan={span && span.rows > 1 ? span.rows : undefined}
                            onClick={() => setSelectedCell({ row: rIdx, col: cIdx, val: cellVal })}
                            style={{ ...(css || {}), ...(width !== undefined && !span ? { maxWidth: width } : {}),
                                     ...(frozen && !css?.backgroundColor ? { backgroundColor: "#fff" } : {}),
                                     ...(spill ? { overflow: "visible", whiteSpace: "nowrap" } : {}) }}
                            className={`px-2.5 py-1 text-slate-800 transition ${spill ? "" : "truncate"} ${look ? "border-0" : "border-r border-slate-200 max-w-xs"} ${
                              isNum ? "text-right" : "text-left"
                            } ${
                              isSelected
                                ? "ring-2 ring-emerald-600 ring-inset"
                                : ""
                            }`}
                          >
                            {spill ? <span className="relative z-[1] inline-block overflow-hidden align-bottom" style={{ maxWidth: room - 20 }}>{cellVal}</span> : cellVal}
                          </td>
                        );
                      })}
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Bottom Multi-Sheet Tab Bar (Excel Style) */}
        <div className="px-3 py-2 border-t border-slate-300 bg-slate-200/90 flex items-center justify-between gap-2 shrink-0">
          <div className="flex items-center space-x-1 overflow-x-auto scrollbar-thin py-0.5 max-w-4xl">
            {sheetNames.map((name) => {
              const isActive = activeSheet === name;
              return (
                <button
                  key={name}
                  onClick={() => handleSheetChange(name)}
                  className={`px-3 py-1 rounded-t-md text-xs font-medium shrink-0 transition flex items-center space-x-1.5 cursor-pointer border-t border-x ${
                    isActive
                      ? "bg-white text-emerald-800 font-bold border-slate-300 shadow-xs translate-y-0.5"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-50 border-transparent"
                  }`}
                >
                  <span className={`w-2 h-2 rounded-full ${tabColours[name] ? "" : isActive ? "bg-emerald-500" : "bg-slate-400"}`}
                        style={tabColours[name] ? { backgroundColor: tabColours[name] as string } : undefined} />
                  <span>{name}</span>
                </button>
              );
            })}
          </div>

          <div className="text-[11px] text-slate-500 font-sans shrink-0 hidden md:block">
            {searchTerm.trim() ? `${plural(filteredData.length, "matching row")}` : `${plural(sheetData.length, "row")}`}
          </div>
        </div>
      </div>
    </div>
  );
}
