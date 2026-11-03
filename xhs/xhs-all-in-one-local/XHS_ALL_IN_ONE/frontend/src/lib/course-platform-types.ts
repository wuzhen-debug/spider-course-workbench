import type { LibraryDraftReview, LibraryDraftSource } from './course-library-types';
export type PlatformImage={page:number;sha256:string;width:number;height:number};
export type XianyuReview={title:string;description:string;price:string|null;delivery_note:string;brand_id:string;source:LibraryDraftSource;
  images:PlatformImage[];row_version:number;status:'pending'|'exported';service_draft_id:number|null;created_at:string};
export type PlatformPair={id:number;file_id:number;revision_id:number;source:LibraryDraftSource;xhs:LibraryDraftReview;xhs_history:number[];
  xianyu:XianyuReview;xianyu_history:{row_version:number;title:string;status:string;created_at:string}[];created_at:string;updated_at:string};
export type PlatformPairSummary={id:number;title:string;brand:string;xhs_package_id:number;xianyu_version:number;created_at:string};
