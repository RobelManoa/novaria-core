import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";
import { describe, expect, it } from "vitest";
import { useFocusTrap } from "@/hooks/useFocusTrap";

function Trap({ active }: { active: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, active);
  return (
    <>
      <button>Extérieur</button>
      <div ref={ref}>
        <a href="#a">Premier</a>
        <button>Dernier</button>
      </div>
    </>
  );
}

describe("useFocusTrap", () => {
  it("boucle de la fin au début avec Tab et du début à la fin avec Maj+Tab", async () => {
    render(<Trap active />);
    await userEvent.tab();
    expect(screen.getByText("Extérieur")).toHaveFocus();

    screen.getByText("Dernier").focus();
    await userEvent.tab();
    expect(screen.getByText("Premier")).toHaveFocus();

    await userEvent.tab({ shift: true });
    expect(screen.getByText("Dernier")).toHaveFocus();
  });

  it("laisse le focus libre quand il est inactif", async () => {
    render(<Trap active={false} />);
    screen.getByText("Dernier").focus();
    await userEvent.tab();
    expect(screen.getByText("Dernier")).not.toHaveFocus();
  });
});
