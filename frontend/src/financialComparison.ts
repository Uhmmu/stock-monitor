export const providerValuesDiffer = (left:number|null, right:number|null) => {
  if(left == null || right == null) return false
  return Math.abs(left-right) > Math.max(Math.abs(left),Math.abs(right),1)*.01
}
