import TailwindAdvancedEditor from "@/components/editor/advanced-editor";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "@/components/editor/ui/dialog";
import Menu from "@/components/editor/ui/menu";
import { ScrollArea } from "@/components/editor/ui/scroll-area";
import { BookOpen } from "lucide-react";
import Link from "next/link";

export default function Page() {
  return (
    <div className="flex min-h-screen flex-col items-center gap-4 py-4 sm:px-5">
      <div className="flex w-full max-w-screen-lg items-center gap-2 px-4 sm:mb-[calc(20vh)]">
        <Button size="icon" variant="outline">
          <a href="https://github.com/steven-tey/novel" target="_blank" rel="noreferrer">            
          </a>
        </Button>
        <Dialog>
          <DialogTrigger asChild>
            <Button className="ml gap-2">
              <BookOpen className="h-4 w-4" />
              Usage in dialog
            </Button>
          </DialogTrigger>
          <DialogContent className="flex max-w-3xl h-[calc(100vh-24px)]">
            <ScrollArea className="max-h-screen">
              <TailwindAdvancedEditor />
            </ScrollArea>
          </DialogContent>
        </Dialog>
        <Link href="/docs" className="ml-auto">
          <Button variant="ghost">Documentation</Button>
        </Link>
        <Menu />
      </div>
      <TailwindAdvancedEditor />
    </div>
  );
}