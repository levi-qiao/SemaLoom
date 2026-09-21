import { test, expect } from '@playwright/test';
import { canonicalMetric } from '../src/doc';

for (const width of [390, 1280]) {
  test(`graph remains usable at ${width}px and toolbar cannot cover labels`, async ({ page }) => {
    await page.setViewportSize({width, height: 844});
    await page.goto('/studio/?view=graph');
    await expect(page.locator('.flow-node').first()).toBeVisible();
    const board=page.locator('.react-flow');
    await expect.poll(async()=> (await board.boundingBox())?.height ?? 0).toBeGreaterThan(300);
    await page.getByRole('button',{name:'适应画布',exact:true}).click();
    await expect.poll(async()=>page.evaluate(()=>{
      const canvas=document.querySelector('.react-flow')!.getBoundingClientRect();
      const toolbar=document.querySelector('.canvas-tools')!.getBoundingClientRect();
      const labels=[...document.querySelectorAll('.edge-label')].map(e=>e.getBoundingClientRect());
      const nodes=[...document.querySelectorAll('.flow-node')].map(e=>e.getBoundingClientRect());
      return toolbar.bottom<=canvas.top && nodes.every(r=>r.left>=canvas.left && r.right<=canvas.right && r.top>=canvas.top && r.bottom<=canvas.bottom)
        && labels.every(r=>r.top>=toolbar.bottom);
    })).toBe(true);
    await page.getByRole('button',{name:'＋ 新建实体',exact:true}).click();
    await expect(page.getByText('新建实体',{exact:true})).toBeVisible();
  });
}


test('editing ordinary metric fields preserves enterprise aliases and statistical scope', () => {
  const population={unitProperty:'facilityId',scopeProperties:['year'],description:'Authorized facilities'};
  const before={id:'operations.output',kind:'Metric',objectType:'operations.Facility',unit:'EA',grain:['facilityId'],aliases:['产量'],population};
  const saved=canonicalMetric({...before,label:'年度产出'});
  expect(saved.population).toEqual(population);
  expect(saved.aliases).toEqual(['产量']);
});


test('automatic layout routes orthogonally with disjoint entity and relationship labels', async ({page}, testInfo) => {
  await page.goto('/studio/?view=graph');
  await expect(page.locator('.edge-label').first()).toBeVisible();
  const inspect = () => page.evaluate(() => {
    const boxes = [...document.querySelectorAll('.flow-node,.edge-label')].map(element => ({text:element.textContent, rect:element.getBoundingClientRect()}));
    const overlaps:string[] = [];
    for(let i=0;i<boxes.length;i++) for(let j=i+1;j<boxes.length;j++) {
      const a=boxes[i].rect,b=boxes[j].rect;
      if(a.left < b.right-1 && a.right > b.left+1 && a.top < b.bottom-1 && a.bottom > b.top+1) overlaps.push(`${boxes[i].text} / ${boxes[j].text}`);
    }
    const paths=[...document.querySelectorAll('.react-flow__edge-path')].map(element=>element.getAttribute('d')??'');
    return {overlaps, paths, labels:document.querySelectorAll('.edge-label').length};
  });
  await expect.poll(async()=> (await inspect()).overlaps).toEqual([]);
  const result=await inspect();
  expect(result.paths.length).toBe(result.labels);
  expect(result.paths.length).toBeGreaterThan(0);
  for(const path of result.paths) {
    expect(path).not.toMatch(/[QC]/);
    const points=[...path.matchAll(/[ML]\s*([\d.-]+),([\d.-]+)/g)].map(match=>[Number(match[1]),Number(match[2])]);
    expect(points.length).toBeGreaterThanOrEqual(2);
    for(let i=1;i<points.length;i++) expect(points[i][0]===points[i-1][0] || points[i][1]===points[i-1][1]).toBe(true);
  }
  await page.screenshot({path:testInfo.outputPath('orthogonal-layout.png')});
  const before=await page.locator('.react-flow__node').first().boundingBox();
  await page.locator('.flow-node').first().click();
  await expect.poll(async()=> (await inspect()).overlaps).toEqual([]);
  expect(before).not.toBeNull();
  await page.getByRole('button',{name:'自动整理',exact:true}).click();
  await expect(page.getByRole('button',{name:'自动整理',exact:true})).toBeEnabled();
  await expect.poll(async()=> (await inspect()).overlaps).toEqual([]);
});

for (const count of [60, 200]) {
  test(`layout handles ${count} configured entities without node or label overlap`, async () => {
    const {layoutGraph,entitySize}=await import('../src/graphLayout');
    const nodes=Array.from({length:count},(_,index)=>({id:`operations.entity${index}`,label:`业务实体 ${index}`,namespace:'operations',properties:[],metricCount:0,ruleCount:0,actionCount:0,mappingCount:0,sourceCount:0}));
    const edges=nodes.slice(1).map((node,index)=>({id:`operations.link${index}`,source:node.id,target:nodes[Math.floor(index/3)].id,label:`业务归属 ${index}`,cardinality:'ONE',sourceKey:'id',targetKey:'id'}));
    const result=await layoutGraph(nodes,edges);
    expect(result.positions.size).toBe(count);
    expect(result.routes.size).toBe(edges.length);
    const boxes=[...nodes.map(node=>({...result.positions.get(node.id)!,...entitySize(node.label)})),...Array.from(result.routes.values(),route=>({...route.label,width:route.width,height:route.height}))];
    const overlaps:number[][]=[];
    for(let i=0;i<boxes.length;i++) for(let j=i+1;j<boxes.length;j++) {
      const a=boxes[i],b=boxes[j];
      if(a.x<b.x+b.width && b.x<a.x+a.width && a.y<b.y+b.height && b.y<a.y+a.height) overlaps.push([i,j]);
    }
    expect(overlaps).toEqual([]);
  });
}

test('manual movement preserves position and connection toolbar opens real link editor', async ({page}) => {
  await page.goto('/studio/?view=graph');
  const first=page.locator('.flow-node').first();
  await expect(first).toBeVisible();
  await expect(page.locator('.edge-label').first()).toBeVisible();
  const before=await first.boundingBox();
  await page.mouse.move(before!.x+before!.width/2,before!.y+before!.height/2);
  await page.mouse.down();
  await page.mouse.move(before!.x+before!.width/2+40,before!.y+before!.height/2+60,{steps:10});
  await page.mouse.up();
  await expect(page.getByText('位置已手动调整；可用“自动整理”重新避让连线与标签。')).toBeVisible();
  const moved=await first.boundingBox();
  expect(Math.hypot(moved!.x-before!.x,moved!.y-before!.y)).toBeGreaterThan(20);
  await page.getByRole('button',{name:'自动整理',exact:true}).click();
  await expect(page.getByText('位置已手动调整；可用“自动整理”重新避让连线与标签。')).toHaveCount(0);
  await page.getByRole('button',{name:'连接实体',exact:true}).click();
  await first.click();
  await page.locator('.flow-node').last().click();
  await expect(page.getByRole('complementary',{name:'关系',exact:true})).toBeVisible();
  await expect(page.getByLabel('显示名称')).toHaveValue('关联');
});
