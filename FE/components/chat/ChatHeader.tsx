import { MessageCircle, StickyNote } from "lucide-react";

export function ChatHeader() {
  return (
    <div>
      <div className="sticky top-0 z-20 bg-white">
        <div className="flex items-center h-[50px] px-[17px]">
          <div className="flex items-center h-[30px] px-[3px] cursor-pointer hover:bg-[#F4F4F4] hover:rounded-md">
            <img src="/profileDefault.png" className="w-[24px] h-[24px] mr-[8px] rounded-md object-cover" />
            <p className="text-l">어디갔어 이거</p>
          </div>
        </div>
        <div className="flex items-center h-[38px] px-[16px] border-b-2">
          <div className="flex items-center w-[72px] p-[8px] cursor-pointer hover:bg-[#F4F4F4] hover:rounded-t-md">
            <MessageCircle className="w-[16px] mr-[4px]" />
            <p className="text-center text-s-bold">메시지</p>
          </div>
          <div className="flex items-center w-[72px] p-[8px] cursor-pointer hover:bg-[#F4F4F4] hover:rounded-t-md">
            <StickyNote className="w-[16px] mr-[4px]" />
            <p className="text-center text-s-bold">캔버스</p>
          </div>
        </div>
      </div>
    </div>
  );
}
