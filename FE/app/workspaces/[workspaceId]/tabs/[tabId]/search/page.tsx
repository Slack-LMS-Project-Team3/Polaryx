"use client";

import { useSearchParams, useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { searchMessages } from "@/apis/messageApi";

interface SearchMessage {
  msg_id: number;
  sender_id: string;
  nickname: string;
  image: string;
  content: string;
  created_at: string;
  file_url: string | null;
  is_updated: number;
}

export default function MessageSearchPage() {
  const params = useParams();
  const workspaceId = params.workspaceId as string;
  const tabId = params.tabId as string;
  const searchParams = useSearchParams();
  const keyword = searchParams.get("q") || "";
  const [messages, setMessages] = useState<SearchMessage[]>([]);

  useEffect(() => {
    if (!keyword) return;
    searchMessages(workspaceId, tabId, keyword).then((res) => {
    console.log(" 받은 메시지:", res);
      setMessages(res.messages);
    });
  }, [keyword, workspaceId, tabId]);

  return (
    <div className="p-4 text-black w-full h-full overflow-y-auto scrollbar-thin">
      <h1 className="text-xl font-bold mb-4">Message Search Results</h1>
      {keyword ? (
        messages.length ? (
          <ul className="space-y-2">
            {messages.map((m) => (
              <li key={m.msg_id} className="border-b pb-2">
                <div className="font-semibold">{m.nickname}</div>
                <div className="text-sm text-gray-500">
                  {new Date(m.created_at).toLocaleString()}
                </div>
                <div dangerouslySetInnerHTML={{ __html: m.content }} />
              </li>
            ))}
          </ul>
        ) : (
          <p>No results.</p>
        )
      ) : (
        <p>No keyword provided.</p>
      )}
    </div>
  );
}
