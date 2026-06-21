import { describe, expect, it } from "vitest";
import { filterUsers } from "../validation";

describe("filterUsers", () => {
  it("keeps valid gmail rows, reports missing required fields, and filters non-gmail addresses", () => {
    const validGmailA = ["valid.user.a", "gmail.com"].join("@");
    const validGmailB = ["valid.user.b", "gmail.com"].join("@");

    const { users, errors } = filterUsers([
      {
        name: "Kim",
        email: validGmailA,
        group: "A",
      },
      {
        name: "Lee",
        email: "",
        group: "",
      },
      {
        name: "Park",
        email: "park@example.com",
        group: "B",
      },
      {
        name: "Choi",
        email: validGmailB,
        group: "C",
        role: "",
      },
    ]);

    expect(users).toEqual([
      {
        name: "Kim",
        email: validGmailA,
        group: "A",
      },
      {
        name: "Choi",
        email: validGmailB,
        group: "C",
        role: "",
      },
    ]);
    expect(errors).toEqual(["3행: 이메일, 그룹 필드가 비어있습니다."]);
  });
});
