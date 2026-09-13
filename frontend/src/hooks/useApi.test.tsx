import { act,renderHook,waitFor } from '@testing-library/react';
import { it,expect,vi } from 'vitest';
import { useApi } from './useApi';
it('늦게 도착한 이전 범위 응답이 현재 범위를 덮어쓰지 않는다',async()=>{
 const pending:Array<(r:Response)=>void>=[];
 const mock=vi.spyOn(globalThis,'fetch').mockImplementation(()=>new Promise(resolve=>pending.push(resolve)));
 const {result,rerender,unmount}=renderHook(({path})=>useApi<{year:number}>(path),{initialProps:{path:'/dashboard?year=2025'}});
 rerender({path:'/dashboard?year=2024'});
 await act(async()=>{pending[1](new Response('{"year":2024}'));});
 await waitFor(()=>expect(result.current.data?.year).toBe(2024));
 await act(async()=>{pending[0](new Response('{"year":2025}'));});
 expect(result.current.data?.year).toBe(2024);unmount();mock.mockRestore();
});
