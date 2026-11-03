import { FilePdfOutlined, SearchOutlined } from '@ant-design/icons';
import { Button, Space } from 'antd';
import { useSearchParams } from 'react-router-dom';
import { researchLane, researchLaneParams } from '../../../lib/course-topic-research';
import { CourseResearchPanel } from './course-research-panel';
import { CoursePdfTopicPanel } from './course-pdf-topic-panel';

export function CourseTopicResearchPage({directory,onOpenPdf}:{directory:string;onOpenPdf:(id:number)=>void}){
 const [params,setParams]=useSearchParams();const lane=researchLane(params);
 return <div className="course-topic-research">
  <Space className="research-lane-buttons" wrap aria-label="选择选题路线">
   <Button size="large" icon={<FilePdfOutlined/>} aria-pressed={lane==='pdf'} type={lane==='pdf'?'primary':'default'} onClick={()=>setParams(researchLaneParams(params,'pdf'))}>根据PDF选题</Button>
   <Button size="large" icon={<SearchOutlined/>} aria-pressed={lane==='xhs'} type={lane==='xhs'?'primary':'default'} onClick={()=>setParams(researchLaneParams(params,'xhs'))}>根据小红书选题</Button>
  </Space>
  {lane==='pdf'?<CoursePdfTopicPanel directory={directory} onOpenPdf={onOpenPdf}/>:<CourseResearchPanel directory={directory} onOpenPdf={onOpenPdf}/>}
 </div>;
}
