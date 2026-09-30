import { notFound } from "next/navigation";

import { ItemEditor } from "@/features/admin/items/item-editor";

export default async function ItemEditorPage(props: PageProps<"/admin/items/[code]">) {
  const { code } = await props.params;
  if (!/^[a-z0-9_]{2,96}$/.test(code)) notFound();
  return <ItemEditor code={code} />;
}
